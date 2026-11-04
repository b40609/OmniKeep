"""
OmniKeep Ask Brain Engine — Grounded Citations Knowledge Assistant.
Orchestrates hybrid retrieval (sqlite-vec + FTS via RRF) and local LLM inference
(any Ollama-compatible model, e.g. Qwen3) with automated cloud fallback.
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional

import httpx

from app.config import settings
from app.vector import search_hybrid

logger = logging.getLogger("omnikeep.brain")

SYSTEM_PROMPT = """你是一個專業的個人第二大腦知識庫助手（OmniKeep Second Brain）。
請基於下方提供的【知識庫參考文獻】回答使用者的問題。

【回答規範】
1. 嚴格依據文獻：必須完全基於提供的文獻事實回答，不可胡亂編造或加油添醋。若文獻中完全未提及，請誠實告知在知識庫中未找到相關資訊。
2. 引用標記格式：在闡述每一項論點、事實或總結時，請在句末使用方括號標註引用來源編號，例如 [1]、[2] 或 [1][3]。標號必須嚴格對應文獻中的編號。
3. 語意結構清楚：條理分明、重點突出，善用條列與粗體重點。
4. 語言風格：使用繁體中文（台灣習慣用語），語氣專業、極簡、精準高密度。
5. 排版規範：嚴禁使用 LaTeX 數學語法，所有符號與單位一律採用純文字（如 5.5%、35 Hz、>= 90% 等）。
"""


def format_citations_prompt(items: List[Dict[str, Any]]) -> str:
    """Format retrieved items into a structured citations context block."""
    if not items:
        return "【知識庫參考文獻】\n（未檢索到相關文獻）\n"

    blocks = ["【知識庫參考文獻】"]
    for idx, item in enumerate(items, start=1):
        title = item.get("title_l1") or "未命名項目"
        category = item.get("category_name") or "Inbox"
        summary = item.get("summary_l1") or ""
        tags = ", ".join(item.get("tech_tags") or [])
        content = (item.get("content_raw") or "")[:400]
        url = item.get("url") or ""

        block = (
            f"[{idx}] 《{title}》 (分類: {category})\n"
            f"摘要: {summary}\n"
            f"標籤: {tags}\n"
            f"精選內容: {content}\n"
            f"原始連結: {url}\n"
        )
        blocks.append(block)

    return "\n".join(blocks)


async def ask_brain(
    question: str,
    history: Optional[List[Dict[str, str]]] = None,
    limit: int = 5,
    force_cloud: bool = False,
) -> Dict[str, Any]:
    """
    Run grounded citation Q&A over the knowledge base.
    1. Retrieve relevant items using hybrid RRF.
    2. Build context-rich prompt.
    3. Query local Strata/Qwen LLM (or failover to cloud provider).
    """
    clean_q = (question or "").strip()
    if not clean_q:
        return {
            "answer": "請輸入您的問題。",
            "citations": [],
            "model": "none",
            "provider": "none",
        }

    # 1. Hybrid Search over knowledge base
    retrieved_items = await search_hybrid(clean_q, limit=limit, vector_weight=0.55)

    citations = []
    for idx, item in enumerate(retrieved_items, start=1):
        citations.append({
            "citation_index": idx,
            "id": item.get("id"),
            "title": item.get("title_l1"),
            "url": item.get("url"),
            "category_name": item.get("category_name"),
            "summary": item.get("summary_l1"),
            "rrf_score": item.get("rrf_score", 0.0),
            "similarity": item.get("similarity", 0.0),
        })

    context_str = format_citations_prompt(retrieved_items)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Append recent conversation history if provided (up to 4 turns)
    if history:
        for turn in history[-4:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    # Append current question with grounded context
    user_payload = f"{context_str}\n\n【使用者問題】\n{clean_q}"
    messages.append({"role": "user", "content": user_payload})

    answer = ""
    model_used = settings.BRAIN_MODEL
    provider_used = settings.BRAIN_PROVIDER

    # 2. Inference: Try local Ollama / Strata first
    if not force_cloud and settings.BRAIN_PROVIDER in ("ollama", "strata"):
        try:
            ollama_url = settings.BRAIN_BASE_URL.rstrip("/")
            async with httpx.AsyncClient(timeout=45.0) as client:
                res = await client.post(
                    f"{ollama_url}/api/chat",
                    json={
                        "model": settings.BRAIN_MODEL,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": 0.25},
                    },
                )
                if res.status_code == 200:
                    data = res.json()
                    answer = data.get("message", {}).get("content", "").strip()
                    provider_used = "local_ollama_gpu"
                else:
                    logger.warning(f"[AskBrain] Local inference returned status {res.status_code}")
        except Exception as e:
            logger.warning(f"[AskBrain] Local inference failed ({e}), initiating cloud fallback...")

    # 3. Fallback: Cloud provider (Gemini / Agnes or OpenAI Compatible)
    if not answer:
        try:
            from app.providers import get_primary_provider
            primary = get_primary_provider()
            answer = await primary.generate_text(prompt=user_payload, system_prompt=SYSTEM_PROMPT)
            provider_used = "cloud_fallback"
            model_used = getattr(settings, "PRIMARY_MODEL", "cloud-llm")
        except Exception as e:
            logger.error(f"[AskBrain] Cloud fallback also failed: {e}")
            answer = (
                "大腦模型目前暫時無法連線。以下是為您檢索到的相關文獻：\n\n"
                + "\n".join([f"- [{c['citation_index']}] 《{c['title']}》: {c['summary']}" for c in citations])
            )
            provider_used = "retrieval_only"

    return {
        "question": clean_q,
        "answer": answer,
        "citations": citations,
        "model": model_used,
        "provider": provider_used,
    }


def get_brain_status() -> Dict[str, Any]:
    """Check connectivity and readiness of the Ask Brain engine."""
    from app.vector import is_sqlite_vec_available
    ollama_ok = False
    models_available = []

    try:
        ollama_url = settings.BRAIN_BASE_URL.rstrip("/")
        with httpx.Client(timeout=3.0) as client:
            resp = client.get(f"{ollama_url}/api/tags")
            if resp.status_code == 200:
                ollama_ok = True
                data = resp.json()
                models_available = [m.get("name") for m in data.get("models", [])]
    except Exception:
        ollama_ok = False

    return {
        "configured_model": settings.BRAIN_MODEL,
        "configured_provider": settings.BRAIN_PROVIDER,
        "ollama_ready": ollama_ok,
        "available_models": models_available,
        "embedding_model": settings.EMBEDDING_MODEL,
        "sqlite_vec_available": is_sqlite_vec_available(),
        # What the owner entered under 設定 › 個人化 › 本機硬體; empty when not set.
        "device_acceleration": (settings.LOCAL_HARDWARE or "").strip(),
    }
