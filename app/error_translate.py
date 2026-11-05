"""Turn providers' English errors into Chinese the owner can act on.

translate() returns:
  hint             what happened and what to do, in Traditional Chinese
  kind             rate_limit | server | auth | disabled | not_found | quota |
                   connection | blocked | bad_request | other
  action_required  True when retrying cannot help and a person must fix it
                   (a disabled key, a suspended account, an empty balance)
  fix_url          where to fix it, when known
"""
import re
from typing import Any, Dict, Optional, Tuple

# (pattern, kind, hint, action_required, fix_url). First match wins; checked before the status code.
_PATTERNS: Tuple[Tuple[str, str, str, bool, Optional[str]], ...] = (
    (r"token status is unavailable", "disabled",
     "金鑰被停用：到 platform.agnes-ai.com 的 API Keys 頁重新啟用或重建，再把新金鑰貼回來。",
     True, "https://platform.agnes-ai.com/settings/apiKeys"),
    (r"rate limit for free users", "rate_limit",
     "超過免費帳號的每分鐘請求數（Agnes 每把金鑰約每分鐘 10 次）：把請求間隔調到 7 秒以上，或再加一把金鑰輪流用。",
     False, None),
    (r"(api key|token) (has )?expired|expired api key", "disabled",
     "金鑰已過期：到服務商後台建立新金鑰。", True, None),
    (r"(account|organization|user) (has been |is )?(disabled|suspended|banned|deactivated)", "disabled",
     "帳號被停用或停權：要登入服務商後台處理，或聯絡服務商。", True, None),
    (r"insufficient[ _]balance|insufficient[ _]quota|exceeded your current quota|credit balance is too low|payment required",
     "quota", "額度或餘額用完：到服務商後台儲值或升級方案。", True, None),
    (r"resource_exhausted|quota exceeded|exceeded.*quota", "rate_limit",
     "免費額度暫時用完（每分鐘或每日上限）：稍後會自動再試；常常發生的話，加一條備援連線。", False, None),
    (r"incorrect api key|invalid api key|invalid_api_key|api key not valid|invalid authentication|unauthorized|authentication fails|invalid x-api-key",
     "auth", "金鑰錯誤：重新貼上金鑰（注意不要多複製到空白或換行），或確認這把金鑰屬於這個服務商。", False, None),
    (r"model[_ ]not[_ ]found|model .*(does not exist|not found|is not available)|no such model|unknown model|invalid model",
     "not_found", "模型名稱不存在或這把金鑰不能用：按「測試」列出可用的模型再選。", False, None),
    (r"context[_ ]length|maximum context|too many tokens|prompt is too long", "bad_request",
     "內容超過模型能處理的長度：改用 context 較長的模型。", False, None),
    (r"response_format|json_object|json mode", "bad_request",
     "這個模型不支援 JSON 格式參數：OmniKeep 會改用一般請求再解析。", False, None),
    (r"网络封锁|blockpage|轉址頁面|封鎖", "blocked",
     "網路被攔截（公司防火牆或代理）：換一個網路，或改用其他服務商。", False, None),
)

_BY_STATUS = (
    (lambda s: s in (401,), "auth", "金鑰無效、已停用，或沒有這項權限：重新貼上金鑰再測試。"),
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
    elif status is None and name in ("JSONDecodeError", "ValueError", "KeyError", "TypeError"):
        info = {"kind": "other", "hint": "模型回應的格式不對（不是有效的 JSON）：換一個模型或服務商通常就能解決。",
                "action_required": False, "fix_url": None}
    return {**info, "status": status}
