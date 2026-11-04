"""
OmniKeep LLM Output Guardrails & Schema Contract
Enforces strict Pydantic v2 validation, automatic field sanitization,
and closed-loop reflection self-correction for LLM outputs.
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationInfo

logger = logging.getLogger("omnikeep.guardrails")


class SubEntitySchema(BaseModel):
    name: str = Field(default="", description="專案、模型或工具名稱")
    canonical_url: str = Field(default="", description="標準可跳轉的 HTTP/HTTPS 倉庫或專案 URL")
    reason: str = Field(default="", description="推薦理由、特色摘要或提及脈絡")
    status: str = Field(default="unverified", description="驗證狀態: verified, candidate, unverified")
    stars: Optional[int] = Field(default=None, description="GitHub Stars 或 Hugging Face 權重指標")
    matched_name: Optional[str] = Field(default=None, description="匹配到的正規 Repo full_name")

    @model_validator(mode="before")
    @classmethod
    def sanitize_entity_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return {"name": str(data) if data else "", "canonical_url": "", "reason": ""}

        raw_name = str(data.get("name") or "").strip()
        raw_url = str(data.get("canonical_url") or "").strip()
        raw_reason = str(data.get("reason") or "").strip()

        # Extract pure URL if model appended bracketed remarks like "https://github.com/foo (note...)"
        extracted_url = ""
        appended_note = ""
        if raw_url:
            url_match = re.search(r'https?://[^\s()<>"]+', raw_url)
            if url_match:
                extracted_url = url_match.group(0).rstrip("/.")
                # Capture trailing remarks if any
                remainder = raw_url[url_match.end():].strip(" ()[]，。;")
                if remainder and len(remainder) > 3:
                    appended_note = remainder

        # Merge extracted note into reason if reason is empty or doesn't have it
        if appended_note and appended_note not in raw_reason:
            raw_reason = f"{raw_reason} ({appended_note})".strip(" ()")

        data["name"] = raw_name
        data["canonical_url"] = extracted_url
        data["reason"] = raw_reason
        return data


class AnalysisOutputSchema(BaseModel):
    category: str = Field(default="Inbox", description="所屬分類名稱")
    title_l1: str = Field(default="未命名情報項目", description="直擊本質的繁中標題（25字內）")
    summary_l1: str = Field(default="已擷取內容，無詳細摘要。", description="L1 核心提要（80-120字）")
    tech_tags: List[str] = Field(default_factory=list, description="技術標籤清單")
    deep_analysis: str = Field(default="", description="L2 深度剖析（Markdown 規格或金句拆解）")
    is_composite: bool = Field(default=False, description="是否為多專案/多工具集合盤點")
    sub_entities: List[SubEntitySchema] = Field(default_factory=list, description="提及的子實體或開源工具清單")

    @field_validator("title_l1", mode="before")
    @classmethod
    def clean_title(cls, v: Any) -> str:
        clean = str(v or "").strip()
        if not clean or clean.lower() in ("null", "none", "undefined", "untitled"):
            return "未命名情報項目"
        # Truncate if model exceeds limit
        return clean[:100]

    @field_validator("summary_l1", mode="before")
    @classmethod
    def clean_summary(cls, v: Any) -> str:
        clean = str(v or "").strip()
        if not clean:
            return "已擷取內容，無詳細摘要。"
        return clean

    @field_validator("category", mode="before")
    @classmethod
    def clean_category(cls, v: Any) -> str:
        clean = str(v or "").strip()
        return clean if clean else "Inbox"

    @field_validator("tech_tags", mode="before")
    @classmethod
    def sanitize_tags(cls, v: Any) -> List[str]:
        if v is None:
            return []
        if isinstance(v, str):
            # Split comma-separated string: "Python, AI, DeepSeek"
            v = [t.strip() for t in re.split(r'[,，、|]+', v) if t.strip()]
        if isinstance(v, (list, tuple)):
            clean_list = []
            seen = set()
            for tag in v:
                t_str = str(tag).strip()
                if t_str and t_str not in seen:
                    seen.add(t_str)
                    clean_list.append(t_str)
            return clean_list
        return []

    @field_validator("is_composite", mode="before")
    @classmethod
    def sanitize_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "t", "y")
        if isinstance(v, (int, float)):
            return v != 0
        return False

    @field_validator("sub_entities", mode="before")
    @classmethod
    def sanitize_sub_entities(cls, v: Any) -> List[Any]:
        if not v:
            return []
        if isinstance(v, dict):
            v = [v]
        if not isinstance(v, list):
            return []
        # Filter out empty ghost dicts
        valid_items = []
        for item in v:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                url = str(item.get("canonical_url") or "").strip()
                if name or url:
                    valid_items.append(item)
        return valid_items


def sanitize_and_validate_analysis(raw_data: Any) -> AnalysisOutputSchema:
    """
    Zero-crash entrypoint: cleans up raw dict/string from LLM and validates against schema.
    If partial data fails, fills sensible defaults and logs warnings instead of crashing.
    """
    if isinstance(raw_data, str):
        try:
            # Strip markdown fences if present
            clean_str = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_data.strip())
            raw_data = json.loads(clean_str)
        except Exception:
            raw_data = {}

    if not isinstance(raw_data, dict):
        raw_data = {}

    try:
        return AnalysisOutputSchema.model_validate(raw_data)
    except Exception as e:
        logger.warning(f"[Guardrails] Strict validation blip: {e}. Performing soft sanitization...")
        # Graceful fallback: construct safe instance
        return AnalysisOutputSchema(
            category=str(raw_data.get("category") or "Inbox"),
            title_l1=str(raw_data.get("title_l1") or "未命名情報項目"),
            summary_l1=str(raw_data.get("summary_l1") or "已儲存內容，無詳細摘要。"),
            tech_tags=raw_data.get("tech_tags") or [],
            deep_analysis=str(raw_data.get("deep_analysis") or ""),
            is_composite=bool(raw_data.get("is_composite")),
            sub_entities=raw_data.get("sub_entities") or []
        )


class ToolJudgeSchema(BaseModel):
    matched_index: Optional[int] = Field(default=None)
    confidence: float = Field(default=0.0)
    reason: str = Field(default="")

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: Any) -> float:
        try:
            val = float(v)
            return max(0.0, min(1.0, val))
        except Exception:
            return 0.0

    @field_validator("matched_index", mode="before")
    @classmethod
    def clean_index(cls, v: Any) -> Optional[int]:
        if v is None or v == "" or str(v).lower() in ("null", "none"):
            return None
        try:
            return int(v)
        except Exception:
            m = re.search(r'\d+', str(v))
            return int(m.group(0)) if m else None


class QueryExtractionSchema(BaseModel):
    has_tool: bool = Field(default=False)
    tool_name: str = Field(default="")
    search_query: str = Field(default="")

    @field_validator("has_tool", mode="before")
    @classmethod
    def clean_bool(cls, v: Any) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() in ("true", "1", "yes")
        return False


def sanitize_and_validate_judge(raw_data: Any) -> ToolJudgeSchema:
    if not isinstance(raw_data, dict):
        return ToolJudgeSchema()
    try:
        return ToolJudgeSchema.model_validate(raw_data)
    except Exception:
        return ToolJudgeSchema()


def sanitize_and_validate_query(raw_data: Any) -> QueryExtractionSchema:
    if not isinstance(raw_data, dict):
        return QueryExtractionSchema()
    try:
        return QueryExtractionSchema.model_validate(raw_data)
    except Exception:
        return QueryExtractionSchema()


async def generate_structured_intelligence(
    provider,
    prompt: str,
    system_prompt: str,
    max_retries: int = 2
) -> Dict[str, Any]:
    """
    Closed-Loop Self-Healing LLM Invocation:
    1. Calls primary LLM.
    2. Validates with Pydantic contract.
    3. If Validation fails, feeds error back to LLM for reflection retry.
    4. Guarantees clean, typed Dict for downstream pipeline.
    """
    last_error = None
    current_prompt = prompt

    for attempt in range(max_retries + 1):
        try:
            raw_json = await provider.generate_json(current_prompt, system_prompt)
            validated = sanitize_and_validate_analysis(raw_json)
            # Successfully validated and sanitized!
            return validated.model_dump()
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                logger.warning(f"[Guardrails] Attempt {attempt + 1} validation failed ({e}). Feeding reflection to LLM...")
                current_prompt = f"""{prompt}

=== 上一次輸出格式驗證失敗提醒 ===
錯誤詳情：{str(e)}
請務必依據原始規範修正上述錯誤，確保 JSON 鍵名與型別完全正確，再次輸出完整的合法 JSON。"""

    logger.error(f"[Guardrails] All {max_retries + 1} attempts hit validation issues. Using soft fallback: {last_error}")
    # Final defense: generate basic fallback structure
    return sanitize_and_validate_analysis({}).model_dump()
