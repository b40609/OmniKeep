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


MAX_HISTORY_TURNS = 4
MAX_HISTORY_CHARS = 2000  # per turn, so a long earlier answer cannot crowd out the citations


# Shown with the answer when the vector side took no part in finding the citations.
SEMANTIC_OFF_NOTICES = {
    "embedding_unreachable": "語意搜尋目前沒有運作（向量模型沒有回應），這次只用關鍵字找收藏，用詞不同的相關內容可能找不到。"
                             "請到「設定 › AI 服務商」確認向量模型的連線。",
    "model_mismatch": "語意搜尋目前沒有運作（大部分收藏的語意索引是用另一個向量模型建立的），這次只用關鍵字找收藏。"
                      "重建語意索引後就會恢復。",
}


def retrieval_report(items: Any) -> Dict[str, Any]:
    """How the citations were found, for the answer's `retrieval` field: `semantic` is
    "ok", "partial", "empty" or "unavailable" (app.vector.semantic_state), and `notice`
    is the sentence to show the person when the semantic side was left out."""
    semantic = getattr(items, "semantic", None) or {}
    state = semantic.get("state", "ok")
    report = {"semantic": state, "reason": semantic.get("reason", ""),
              "query_model": semantic.get("query_model", ""), "index_model": semantic.get("index_model", ""),
              "not_indexed": semantic.get("not_indexed", 0), "notice": ""}
    if state == "unavailable":
        report["notice"] = SEMANTIC_OFF_NOTICES.get(report["reason"], SEMANTIC_OFF_NOTICES["embedding_unreachable"])
    return report


def _with_history(turns: List[Dict[str, str]], user_payload: str) -> str:
    """The cloud fallback takes a single prompt, so earlier turns go in as text."""
    if not turns:
        return user_payload
    names = {"user": "使用者", "assistant": "助手"}
    lines = ["【先前對話】"] + [f"{names[t['role']]}：{t['content']}" for t in turns]
    return "\n".join(lines) + "\n\n" + user_payload


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
            "retrieval": retrieval_report(None),
            "notice": "",
        }

    limit = max(1, min(int(limit or 1), settings.BRAIN_MAX_CITATIONS))

    # 1. Hybrid Search over knowledge base
    retrieved_items = await search_hybrid(clean_q, limit=limit, vector_weight=0.55, usable_only=True)
    retrieval = retrieval_report(retrieved_items)
    if not retrieved_items:
        # Nothing to cite: a model asked anyway makes up an answer and its sources.
        return {
            "question": clean_q,
            "answer": "還沒有相關的收藏，所以沒有可以引用的內容。先收藏幾則相關的連結再問一次。",
            "citations": [],
            "model": "none",
            "provider": "retrieval_only",
            "retrieval": retrieval,
            "notice": retrieval["notice"],
        }

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

    # Append recent conversation history if provided (up to 4 turns, each capped)
    recent_turns = []
    if history:
        for turn in history[-MAX_HISTORY_TURNS:]:
            role = turn.get("role")
            content = (turn.get("content") or "")[:MAX_HISTORY_CHARS]
            if role in ("user", "assistant") and content:
                recent_turns.append({"role": role, "content": content})
    messages.extend(recent_turns)

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
                        "options": {"temperature": 0.25, "num_ctx": settings.BRAIN_NUM_CTX},
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
            from app.providers import get_provider
            primary = get_provider("brain", skip_kinds=("ollama",))  # local Ollama was tried above
            answer = await primary.generate_text(
                prompt=_with_history(recent_turns, user_payload), system_prompt=SYSTEM_PROMPT)
            provider_used = "cloud_fallback"
            model_used = getattr(settings, "PRIMARY_MODEL", "cloud-llm")
        except Exception as e:
            logger.error(f"[AskBrain] Cloud fallback also failed: {e}")
            if citations:
                answer = (
                    "AI 目前連不上，沒有產生回答。以下是找到的相關收藏：\n\n"
                    + "\n".join([f"- [{c['citation_index']}] 《{c['title']}》: {c['summary']}" for c in citations])
                )
            else:
                answer = "AI 目前連不上，沒有產生回答，也沒有找到相關的收藏。請到「設定 › AI」確認連線後再試一次。"
            provider_used = "retrieval_only"

    return {
        "question": clean_q,
        "answer": answer,
        "citations": citations,
        "model": model_used,
        "provider": provider_used,
        # How the citations were found. `notice` is non-empty when the person has to be
        # told that semantic search took no part (the same text as retrieval["notice"]).
        "retrieval": retrieval,
        "notice": retrieval["notice"],
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
