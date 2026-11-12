"""Turn providers' English errors into Chinese the owner can act on.

translate() returns:
  hint             what happened and what to do, in Traditional Chinese
  kind             rate_limit | server | auth | disabled | not_found | quota |
                   connection | blocked | bad_request | empty | invalid_output | no_ai | other
  action_required  True when retrying cannot help and a person must fix it
                   (a disabled key, a suspended account, an empty balance)
  fix_url          where to fix it, when known

failure_message() is what the person who sent a link reads when its analysis failed
(Telegram, LINE, the ingest API, an agent); is_ai_failure() tells the AI's failure from
a failed fetch of the page.
"""
import re
from typing import Any, Dict, Optional, Tuple

_FREE_TIER_USED_UP = "免費額度暫時用完（每分鐘或每日上限）：稍後會自動再試；常常發生的話，加一條備援連線。"

# (pattern, kind, hint, action_required, fix_url). First match wins; checked before the status code.
_PATTERNS: Tuple[Tuple[str, str, str, bool, Optional[str]], ...] = (
    (r"token status is unavailable", "disabled",
     "金鑰被停用：到 platform.agnes-ai.com 的 API Keys 頁重新啟用或重建，再把新金鑰貼回來。",
     True, "https://platform.agnes-ai.com/settings/apiKeys"),
    (r"rate limit for free users", "rate_limit",
     "超過免費帳號的每分鐘請求數（Agnes 每把金鑰約每分鐘 10 次）：把請求間隔調到 7 秒以上，或再加一把金鑰輪流用。",
     False, None),
    # Before the balance rule below: a Gemini rate limit is worded "You exceeded your current
    # quota, please check your plan and billing details" too, and only its RESOURCE_EXHAUSTED
    # status tells it from an empty balance. Taken for one, the key was marked as needing a
    # person and the fallback chain stopped using it.
    (r"resource_exhausted", "rate_limit", _FREE_TIER_USED_UP, False, None),
    (r"(api key|token) (has )?expired|expired api key", "disabled",
     "金鑰已過期：到服務商後台建立新金鑰。", True, None),
    (r"(account|organization|user) (has been |is )?(disabled|suspended|banned|deactivated)", "disabled",
     "帳號被停用或停權：要登入服務商後台處理，或聯絡服務商。", True, None),
    (r"insufficient[ _]balance|insufficient[ _]quota|exceeded your current quota|credit balance is too low|payment required",
     "quota", "額度或餘額用完：到服務商後台儲值或升級方案。", True, None),
    (r"quota exceeded|exceeded.*quota", "rate_limit", _FREE_TIER_USED_UP, False, None),
    (r"incorrect api key|invalid api key|invalid token|invalid_api_key|api key not valid|invalid authentication|unauthorized|authentication fails|invalid x-api-key",
     "auth", "金鑰錯誤：到「設定 › AI」檢查這條連線的金鑰（注意不要多複製到空白或換行），或確認這把金鑰屬於這個服務商。", False, None),
    (r"model[_ ]not[_ ]found|model .*(does not exist|not found|is not available)|no such model|unknown model|invalid model",
     "not_found", "模型名稱不存在或這把金鑰不能用：按「測試」列出可用的模型再選。", False, None),
    (r"context[_ ]length|maximum context|too many tokens|prompt is too long", "bad_request",
     "內容超過模型能處理的長度：改用 context 較長的模型。", False, None),
    (r"response_format|json_object|json mode", "bad_request",
     "這個模型不支援 JSON 格式參數：OmniKeep 會改用一般請求再解析。", False, None),
    (r"网络封锁|blockpage|轉址頁面|封鎖", "blocked",
     "網路被攔截（公司防火牆或代理）：換一個網路，或改用其他服務商。", False, None),
    # app.providers.base.EmptyResponseError
    (r"空白內容", "empty",
     "模型回了空白內容（推理型模型把輸出都用在思考時常見）：換一個模型，或在這條連線的「額外請求參數」關閉推理。",
     False, None),
)

# What to say once an analysis has failed for good. The hints of these kinds are written for
# the connection's status in the settings page and promise an automatic retry; by the time
# a person reads the failure, that retry is over.
_FAILED_FOR_GOOD = {
    "rate_limit": "AI 服務限流（請求太頻繁，或免費額度暫時用完）：過幾分鐘再試一次；"
                  "常發生的話到「設定 › AI」把請求間隔調長，或加一條備援連線。",
    "server": "AI 服務商暫時故障：過幾分鐘再試一次，或到「設定 › AI」加一條備援連線。",
    "connection": "連不上 AI 服務（連線失敗或逾時）：確認網路和服務位址，本機的服務要先啟動，再試一次。",
}

# Exceptions of the AI layer, by where their class lives: the SDKs, and OmniKeep's own
# (matched by name, so this module stays importable without loading the providers).
_AI_SDK_PACKAGES = ("openai", "google.genai", "google.api_core")
_AI_ERROR_NAMES = ("ProviderUnavailableError", "EmptyResponseError", "AnalysisFailedError", "NoAIConnectionError")
_AI_MARK = "_omnikeep_ai_failure"

_BY_STATUS = (
    (lambda s: s in (401,), "auth", "金鑰無效、已停用，或沒有這項權限：到「設定 › AI」檢查這條連線的金鑰再測試。"),
    (lambda s: s == 402, "quota", "需要付款或儲值：到服務商後台處理。"),
    (lambda s: s == 403, "auth", "沒有權限：金鑰沒有這個模型或功能的權限，或帳號受限。"),
    (lambda s: s == 404, "not_found", "找不到：API 位址或模型名稱可能有誤，按「測試」確認。"),
    (lambda s: s == 408, "connection", "服務商回應逾時：稍後會自動再試。"),
    (lambda s: s == 429, "rate_limit", "請求太頻繁或額度暫時用完：會自動放慢並在冷卻後再試；常發生的話把請求間隔調長。"),
    (lambda s: s is not None and s >= 500, "server", "服務商暫時故障：稍後會自動再試，期間改用備援連線。"),
    (lambda s: s is not None and s >= 400, "bad_request", "服務商拒絕這個請求（HTTP {status}）。"),
)


def translate(status: Optional[int], message: str = "") -> Dict[str, Any]:
    text = (message or "").lower()
    for pattern, kind, hint, action, url in _PATTERNS:
        if re.search(pattern, text):
            return {"kind": kind, "hint": hint, "action_required": action, "fix_url": url}
    if status is None:
        if any(word in text for word in ("timed out", "timeout", "逾時")):
            return {"kind": "connection", "hint": "連線逾時：服務商太慢或網路不穩，稍後會自動再試。",
                    "action_required": False, "fix_url": None}
        return {"kind": "connection", "hint": "連不上服務商：確認位址正確、網路正常；本機服務要先啟動。",
                "action_required": False, "fix_url": None}
    for test, kind, hint in _BY_STATUS:
        if test(status):
            return {"kind": kind, "hint": hint.format(status=status), "action_required": False, "fix_url": None}
    return {"kind": "other", "hint": f"服務商回應 HTTP {status}。", "action_required": False, "fix_url": None}


def status_of(exc: BaseException) -> Optional[int]:
    """HTTP status carried by an SDK exception (openai, google-genai, httpx), if any."""
    for attr in ("status_code", "code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int) and 100 <= value < 600:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def classify(exc: BaseException) -> Dict[str, Any]:
    """translate() for an exception, plus its status."""
    status = status_of(exc)
    name = type(exc).__name__
    if status is None and name in ("RateLimitError",):
        status = 429
    info = translate(status, f"{name}: {exc}")
    if name in ("ProviderUnavailableError",):
        info = {"kind": "blocked", "hint": translate(None, "封鎖")["hint"], "action_required": False, "fix_url": None}
    elif name == "EmptyResponseError":
        info = translate(None, "空白內容")
    elif name == "NoAIConnectionError":  # app.providers.base: nothing was sent, there is no key to fix
        info = {"kind": "no_ai", "hint": str(exc), "action_required": True, "fix_url": None}
    elif name == "AnalysisFailedError":  # app.schemas.intelligence: its message is the explanation
        info = {"kind": "invalid_output", "hint": str(exc), "action_required": False, "fix_url": None}
    elif status is None and name in ("JSONDecodeError", "ValueError", "KeyError", "TypeError"):
        info = {"kind": "other", "hint": "模型回應的格式不對（不是有效的 JSON）：換一個模型或服務商通常就能解決。",
                "action_required": False, "fix_url": None}
    return {**info, "status": status}


def mark_ai_failure(exc: BaseException) -> BaseException:
    """Called where the pipeline asks the AI for an analysis: whatever fails there is the AI's
    failure, whatever its type (google-genai lets plain httpx errors through). The exception
    goes on unchanged; is_ai_failure() reads the mark."""
    try:
        setattr(exc, _AI_MARK, True)
    except Exception:  # a type without a __dict__: its class decides
        pass
    return exc


def is_ai_failure(exc: BaseException) -> bool:
    """True for a failed AI call, False for anything else, such as the fetch of the page: a
    site answering 429 or timing out says nothing about the AI quota."""
    if getattr(exc, _AI_MARK, False):
        return True
    cls = type(exc)
    module = cls.__module__ or ""
    return cls.__name__ in _AI_ERROR_NAMES or any(
        module == package or module.startswith(package + ".") for package in _AI_SDK_PACKAGES)


def failure_message(exc: BaseException) -> str:
    """Why an item was not saved, for the person (or agent) who sent it.

    An AI failure is explained in Chinese with what to do about it. Anything else keeps its
    own message: the parsers already raise theirs in Chinese.
    """
    if not is_ai_failure(exc):
        return str(exc).strip() or type(exc).__name__
    info = classify(exc)
    return "AI 分析失敗：" + (_FAILED_FOR_GOOD.get(info["kind"]) or info["hint"])
