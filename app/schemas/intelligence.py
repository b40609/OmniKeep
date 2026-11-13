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

_CJK = r"[㐀-鿿＀-￯「」]"
_CODE = re.compile(r"(```.*?```|`[^`\n]*`)", re.S)


def _full_width(text: str) -> str:
    for half, full in ((",", "，"), (":", "："), (";", "；"), ("?", "？"), ("!", "！")):
        text = re.sub(rf"(?<={_CJK}){re.escape(half)}[ \t]*|(?<=[A-Za-z0-9）)]){re.escape(half)}[ \t]*(?={_CJK})", full, text)
    return text


def full_width_punctuation(text: str) -> str:
    """Half-width , : ; ? ! next to Chinese become full-width (the prompt asks for it; free
    models often ignore it). URLs, numbers and anything inside `code` or ``` fences stay."""
    parts = _CODE.split(text or "")
    return "".join(p if i % 2 else _full_width(p) for i, p in enumerate(parts))


_DETAILS_TAG = re.compile(r"[ \t]*(<details>|</details>|<summary>.*?</summary>)[ \t]*")


def _space_details(text: str) -> str:
    text = _DETAILS_TAG.sub(lambda m: f"\n\n{m.group(1)}\n\n", text)
    text = re.sub(r"<details>\s*<summary>", "<details>\n<summary>", text)
    return text


def details_spacing(text: str) -> str:
    """Blank lines around the <details>, <summary> and </details> of the deep analysis (prompt
    v2.4). Without them marked keeps the section's Markdown as raw text; the prompt asks for them
    but models drop them now and then. Code fences are left as they are."""
    if "<details>" not in (text or ""):
        return text or ""
    parts = _CODE.split(text)
    out = "".join(p if i % 2 else _space_details(p) for i, p in enumerate(parts))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _bigrams(text: str) -> set:
    text = re.sub(r"[\s，。：:,、「」（）()！!？?.\-/]", "", text.lower())
    out = set(re.findall(r"[a-z0-9.+#_]{2,}", text))
    cjk = re.sub(r"[a-z0-9.+#_]", "", text)
    return out | {cjk[i:i + 2] for i in range(len(cjk) - 1)}


def title_overlap(title: str, summary: str) -> float:
    """Share of the title's bigrams that come back in the summary's first sentence."""
    first = re.split(r"[。！？]", summary or "")[0]
    grams = _bigrams(title or "")
    return len(grams & _bigrams(first)) / max(len(grams), 1)


def summary_repeats_title(title: str, summary: str) -> bool:
    """The summary's first sentence says again what the title said: the title's name, an
    「X 是一個…」 sentence, or most of the title's words. The owner's blind reviews marked
    this the worst fault of a summary, and the prompt alone did not stop it."""
    name = re.split(r"[：:]", title or "")[0].strip().lower()
    first = re.split(r"[。！？]", summary or "")[0].lower()
    if len(name) >= 2 and (name in first or re.search(r"是(一[個款套種份]|開源)", first)):
        return True
    return title_overlap(title, summary) >= 0.4


def repeat_feedback(title: str, summary: str) -> str:
    return (f"\n\n=== 上一版的問題 ===\n摘要第一句重複了標題。標題：「{title}」；摘要：「{summary}」。\n"
            "請重寫整個 JSON：摘要直接講它交付什麼、關鍵數字與適用對象，不要再出現標題裡的名稱，"
            "也不要用「某某是一個」的句型。")


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
    # Empty when the model gave none: app.pipeline then falls back to the page/video
    # title, the bookmarklet's hints or its own placeholder.
    title_l1: str = Field(default="", description="白話標題：名稱：最吸引人的具體事實或用途（25 字內，英文單字算 1 字）")
    summary_l1: str = Field(default="", description="2 到 3 句、70 到 120 字，不重複標題")
    tech_tags: List[str] = Field(default_factory=list, description="技術標籤清單")
    deep_analysis: str = Field(default="", description="Markdown：> 引言、## 最重要的 3 件事，其餘放 <details> 收合區")
    is_composite: bool = Field(default=False, description="是否為多專案/多工具集合盤點")
    sub_entities: List[SubEntitySchema] = Field(default_factory=list, description="提及的子實體或開源工具清單")

    @field_validator("title_l1", mode="before")
    @classmethod
    def clean_title(cls, v: Any) -> str:
        clean = str(v or "").strip()
        if not clean or clean.lower() in ("null", "none", "undefined", "untitled"):
            return ""
        # Truncate if model exceeds limit
        return full_width_punctuation(clean[:100])

    @field_validator("summary_l1", mode="before")
    @classmethod
    def clean_summary(cls, v: Any) -> str:
        return full_width_punctuation(str(v or "").strip())

    @field_validator("deep_analysis", mode="before")
    @classmethod
    def clean_deep_analysis(cls, v: Any) -> str:
        return details_spacing(full_width_punctuation(str(v or "")))

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
            title_l1=str(raw_data.get("title_l1") or ""),
            summary_l1=str(raw_data.get("summary_l1") or ""),
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


class UnusableAnalysis(ValueError):
    """A model's answer that holds no analysis; the message says what is wrong with it."""


class AnalysisFailedError(Exception):
    """The model answered every time, but never with a usable analysis.

    Raised instead of handing back an empty structure, which the pipeline saved as a finished
    item with a placeholder summary. `reason` is what was wrong with the last answer.
    """

    def __init__(self, reason: str, attempts: int = 1):
        self.reason = reason
        self.attempts = attempts
        super().__init__(f"模型回應了 {attempts} 次，都不是可用的分析（{reason}）：換一個模型或服務商通常就能解決。")


def usable_analysis(raw_data: Any) -> Dict[str, Any]:
    """The validated analysis as a dict; UnusableAnalysis when the answer holds none.

    sanitize_and_validate_analysis() never fails: it turns anything, even None, into a schema
    full of defaults. So an answer with the wrong keys, or no answer at all, used to pass as an
    analysis. One with neither a summary nor a deep analysis is not an analysis.
    """
    if isinstance(raw_data, str):
        try:
            raw_data = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_data.strip()))
        except ValueError:
            raise UnusableAnalysis("輸出不是合法的 JSON") from None
    if not isinstance(raw_data, dict):
        raise UnusableAnalysis(f"輸出不是 JSON 物件（是 {type(raw_data).__name__}）")
    validated = sanitize_and_validate_analysis(raw_data)
    if not validated.summary_l1 and not validated.deep_analysis.strip():
        keys = "、".join(str(k) for k in list(raw_data)[:12])
        raise UnusableAnalysis("沒有 summary_l1 也沒有 deep_analysis" + (f"；收到的鍵：{keys}" if keys else "；輸出是空物件"))
    return validated.model_dump()


async def rewrite_if_summary_repeats_title(provider, prompt: str, system_prompt: str,
                                           result: Dict[str, Any]) -> Dict[str, Any]:
    """Asks once more, with the fault named, when the summary restates the title.

    The first answer is a usable analysis already, so the second call can only improve on it:
    if it fails, does not validate or still repeats more, the first answer is kept.
    """
    title, summary = result.get("title_l1") or "", result.get("summary_l1") or ""
    if not summary_repeats_title(title, summary):
        return result
    try:
        second = usable_analysis(await provider.generate_json(prompt + repeat_feedback(title, summary), system_prompt))
    except Exception as exc:
        logger.info("[Guardrails] Rewrite of a summary that repeats its title failed (%s); keeping the first.", exc)
        return result
    if title_overlap(second["title_l1"] or title, second["summary_l1"]) <= title_overlap(title, summary):
        return second
    return result


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
    3. If the model answered but the answer does not validate, feeds the problem back to
       the LLM for a reflection retry (up to max_retries more calls).
    4. Returns a clean, typed Dict, or raises: AnalysisFailedError when no answer validated,
       the provider's own exception when the call itself failed.

    A provider failure (rate limit, dead key, connection, HTTP error, empty answer) goes up
    at once, untouched. Asking again with a reminder cannot fix it and only spends more of a
    small quota (three calls an item emptied a two-a-minute free tier); the caller has its
    own retry and backoff.
    """
    attempts = max_retries + 1
    problem = ""
    current_prompt = prompt

    for attempt in range(attempts):
        try:
            raw_json = await provider.generate_json(current_prompt, system_prompt)
            return await rewrite_if_summary_repeats_title(provider, prompt, system_prompt, usable_analysis(raw_json))
        except json.JSONDecodeError as e:  # the model answered with text that is not JSON
            problem = f"輸出不是合法的 JSON（{e.msg}）"
        except UnusableAnalysis as e:
            problem = str(e)
        if attempt + 1 < attempts:
            logger.warning(f"[Guardrails] Attempt {attempt + 1} validation failed ({problem}). Feeding reflection to LLM...")
            current_prompt = f"""{prompt}

=== 上一次輸出格式驗證失敗提醒 ===
錯誤詳情：{problem}
請務必依據原始規範修正上述錯誤，確保 JSON 鍵名與型別完全正確，再次輸出完整的合法 JSON。"""

    logger.error(f"[Guardrails] All {attempts} attempts hit validation issues: {problem}")
    raise AnalysisFailedError(problem, attempts)
