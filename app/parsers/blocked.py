"""Tell a site's error or anti-bot page apart from the content the user saved.

A server-side fetch of X, a Cloudflare-protected site or a removed page often gets back a
short page that says "enable JavaScript", "verifying you are human" or "404". Analysed as if
it were the article, it produced a confident deep analysis that was all made up (2026-11-07:
18 X items held only "We've detected that JavaScript is disabled…").

A page counts as blocked only when all of these hold, so a short post that merely mentions
JavaScript or a 404 is not caught:
  1. the text is short (at most MAX_CHARS);
  2. a sentence matches one of the error-page phrases below (STRONG);
  3. once the sentences with error-page phrases or footer boilerplate (NOISE) are removed,
     at most RESIDUAL_LIMIT letters are left, and fewer than were removed.
"""
import re
from typing import Iterable, List, Optional, Pattern, Tuple

MAX_CHARS = 2000
RESIDUAL_LIMIT = 100

# What parse_web_page() stores when it got no text at all.
EMPTY_PLACEHOLDER = "（未能擷取到網頁內文）"

# Why the content is missing, phrased to follow "因為" in a note shown to the reader.
REASONS = {
    "js_required": "網站回的是「請啟用 JavaScript」的頁面",
    "bot_check": "網站回的是機器人驗證頁（例如 Cloudflare）",
    "access_denied": "網站拒絕存取",
    "not_found": "網頁不存在（404）",
    "http_error": "網站回應錯誤",
    "empty": "沒有擷取到任何內文",
}


def _compile(patterns: Iterable[str]) -> List[Pattern[str]]:
    return [re.compile(p, re.IGNORECASE) for p in patterns]


STRONG: List[Tuple[str, List[Pattern[str]]]] = [
    ("js_required", _compile([
        r"javascript (?:is|has been) (?:disabled|not enabled|turned off)",
        r"(?:please|you need to|you must|you'll need to|need to)\s+enable\s+javascript",
        r"enable javascript (?:and cookies )?to (?:continue|run|use|view|access|proceed)",
        r"this (?:app|site|page|website) requires javascript",
        r"your (?:current )?browser (?:is not|isn't|is no longer) (?:compatible|supported)",
        r"(?:請|请|需要|須|必須)(?:先)?(?:啟用|启用|開啟|开启)\s*javascript",
        r"(?:已|被)(?:停用|禁用|關閉|关闭)\s*javascript",
        r"javascript\s*(?:已|被)(?:停用|禁用|關閉|关闭)",
        r"something went wrong\.? (?:try reloading|but don.t fret)",
    ])),
    ("bot_check", _compile([
        r"checking (?:if the site connection is secure|your browser)",
        r"verify(?:ing)? (?:that )?you are (?:a )?human",
        r"are you a (?:human|robot)\?",
        r"needs to review the security of your connection",
        r"attention required!? ?\| ?cloudflare",
        r"performance (?:&|and) security by cloudflare",
        r"ddos protection by",
        r"(?:complete|solve) (?:the|this) (?:captcha|security check)",
        r"press (?:&|and) hold",
        r"unusual traffic from your computer network",
        r"request unsuccessful\. incapsula",
        r"正在(?:執行|进行|進行|执行)安全(?:驗證|验证)",
        r"(?:確認|确认|驗證|验证)您?(?:不是|是否為|是否为)機器人",
        r"(?:確認|确认|驗證|验证)您?是真人",
        r"此網站使用安全服務",
        r"正在(?:检查|檢查)您的(?:浏览器|瀏覽器)",
    ])),
    ("access_denied", _compile([
        r"\baccess denied\b",
        r"access to this page has been denied",
        r"you don.t have permission to access",
        r"\b403 forbidden\b",
        r"\berror 1020\b",
        r"this content isn.t available (?:right now|in your country)",
        r"(?:拒絕|拒绝)存取|禁止存取|(?:访问|訪問)被拒",
    ])),
    ("not_found", _compile([
        r"\b404\b[^.\n]{0,20}not found",
        r"\bpage not found\b",
        r"(?:page|file) (?:you (?:are|were) looking for|you requested) "
        r"(?:could not|can.t|cannot|was not|wasn.t|does not|doesn.t|no longer|is no longer)",
        r"couldn.t find (?:the|that|this) (?:page|file)",
        r"this page (?:could not be found|doesn.t exist|does not exist|is not available)",
        r"deployment_not_found",
        r"may have been moved, removed,? or never existed",
        r"this account doesn.t exist",
        r"(?:找不到|查無)(?:此|該|这个|這個)?(?:頁面|网页|網頁|页面)",
        r"(?:頁面|页面|網頁|网页)不存在",
    ])),
]

# Footer and filler that surround an error page. Removed only once a STRONG phrase matched.
NOISE = _compile([
    r"help center", r"terms of service", r"privacy policy", r"cookie policy", r"\bimprint\b",
    r"ads info", r"©", r"\bray id\b", r"supported browsers?", r"need help\??",
    r"something went wrong", r"try again", r"\breload", r"\b40[0-9]\b", r"\b5[0-9]{2}\b",
    r"not found", r"if you.re lost", r"popular searches", r"cloudflare", r"reference #",
    r"network connection", r"browser outdated", r"go (?:back )?home", r"back to home",
    r"return to (?:the )?home ?page", r"驗證成功|验证成功", r"正在等待", r"重新整理|重新載入",
])

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|(?<=[。！？])")
_NON_LETTERS = re.compile(r"[\W_]+")


def _letters(text: str) -> int:
    return len(_NON_LETTERS.sub("", text))


def detect_blocked_page(text: str, http_status: Optional[int] = None) -> Optional[str]:
    """The REASONS key when `text` is a site's error / anti-bot page rather than content, else None."""
    clean = (text or "").strip()
    if not clean or clean == EMPTY_PLACEHOLDER:
        return "http_error" if http_status and http_status >= 400 else "empty"
    if len(clean) > MAX_CHARS:
        return None

    reason = None
    removed = residual = 0
    for line in clean.splitlines():
        for sentence in _SENTENCE_SPLIT.split(line):
            size = _letters(sentence)
            if not size:
                continue
            hit = next((key for key, patterns in STRONG if any(p.search(sentence) for p in patterns)), None)
            if hit:
                reason = reason or hit
                removed += size
            elif any(p.search(sentence) for p in NOISE):
                removed += size
            else:
                residual += size
    if reason and residual <= RESIDUAL_LIMIT and residual < removed:
        return reason
    return None


def reason_text(reason: str, http_status: Optional[int] = None) -> str:
    if reason == "http_error" and http_status:
        return f"網站回應 HTTP {http_status}，沒有擷取到內文"
    return REASONS.get(reason, REASONS["empty"])


def is_error_title(title: str) -> bool:
    """A page title that names the error page itself (or nothing), so it says nothing about the content."""
    clean = (title or "").strip()
    if len(clean) < 6 or clean in ("未知標題", "未命名項目"):
        return True
    lowered = clean.lower()
    if any(word in lowered for word in ("just a moment", "attention required", "access denied", "403 forbidden",
                                        "page not found", "404", "error", "請稍候", "请稍候")):
        return True
    return any(p.search(clean) for _, patterns in STRONG for p in patterns)
