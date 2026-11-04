"""Try a provider or bot credential from the settings page, before or after saving it.

Values typed in the form are tested as typed; fields left blank fall back to
what is in effect now. Nothing here changes settings or the service status.
"""
from typing import Any, Callable, Dict, List, Optional

from openai import APIConnectionError, APIStatusError, AsyncOpenAI

from app import app_settings
from app.ai_status import redact
from app.config import settings

TIMEOUT = 20.0


def _candidate(values: Dict[str, Any], key: str) -> Any:
    spec = app_settings.SPEC_BY_KEY[key]
    raw = values.get(key)
    if raw not in (None, ""):
        return app_settings.normalize(spec, raw)
    return getattr(settings, spec.field)


def _explain(status: Optional[int]) -> str:
    if status in (401, 403):
        return "金鑰無效、已停用，或沒有這項權限"
    if status == 404:
        return "找不到：API 位址或模型名稱可能有誤"
    if status == 429:
        return "超過額度或請求太頻繁"
    if status is not None and status >= 500:
        return "服務商暫時故障，稍後再試"
    if status is None:
        return "連不上伺服器"
    return f"服務商回應 HTTP {status}"


def _scrub(text: str, secrets: List[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    return redact(text)


def _ok(message: str) -> Dict[str, Any]:
    return {"ok": True, "status": 200, "message": message, "detail": ""}


def _fail(status: Optional[int], detail: str = "", secrets: Optional[List[str]] = None,
          message: str = "") -> Dict[str, Any]:
    return {"ok": False, "status": status, "message": message or _explain(status),
            "detail": _scrub(detail, secrets or [])}


def _guard_base_url(values: Dict[str, Any], base_url: str) -> Optional[Dict[str, Any]]:
    """Never send the saved key to an address it was not saved for."""
    if base_url.rstrip("/") != settings.OPENAI_BASE_URL.rstrip("/") and not values.get("OPENAI_API_KEY"):
        return _fail(None, message="更換 API 位址時，請一併輸入要測試的 API 金鑰")
    return None


async def _check_llm(values: Dict[str, Any]) -> Dict[str, Any]:
    base_url = _candidate(values, "OPENAI_BASE_URL")
    blocked = _guard_base_url(values, base_url)
    if blocked:
        return blocked
    key = _candidate(values, "OPENAI_API_KEY")
    model = _candidate(values, "PRIMARY_MODEL")
    if not key:
        return _fail(None, message="還沒有設定 API 金鑰")
    client = AsyncOpenAI(base_url=base_url, api_key=key, timeout=TIMEOUT, max_retries=0)
    try:
        listed: List[str] = []
        try:
            page = await client.models.list()
            listed = [m.id for m in page.data]
            if model in listed:
                return _ok(f"連線成功，找到模型 {model}")
        except APIStatusError as exc:
            if exc.status_code in (401, 403):
                return _fail(exc.status_code, str(exc), [key])
            # Some compatible servers do not list models; a one-token request settles it.
        await client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": "ping"}], max_tokens=1)
        return _ok(f"連線成功，模型 {model} 可以回應")
    except APIStatusError as exc:
        return _fail(exc.status_code, str(exc), [key])
    except APIConnectionError as exc:
        return _fail(None, f"{type(exc).__name__}: {exc}", [key])
    finally:
        await client.close()


async def _check_embeddings(values: Dict[str, Any]) -> Dict[str, Any]:
    from app.network import UnsafeURL, public_http_client
    base_url = _candidate(values, "OPENAI_BASE_URL")
    blocked = _guard_base_url(values, base_url)
    if blocked:
        return blocked
    key = _candidate(values, "OPENAI_API_KEY")
    model = _candidate(values, "EMBEDDING_MODEL")
    if not key:
        return _fail(None, message="還沒有設定 API 金鑰；語意搜尋會改用本機向量")
    dim = int(settings.EMBEDDING_DIM)
    try:
        async with public_http_client(timeout=TIMEOUT) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {key}"},
                json={"input": "ping", "model": model, "dimensions": dim},
            )
    except UnsafeURL:
        return _fail(None, message="向量服務只能用公開網址；本機或內網位址會改用本機向量")
    except Exception as exc:
        return _fail(None, f"{type(exc).__name__}: {exc}", [key])
    if resp.status_code != 200:
        return _fail(resp.status_code, resp.text[:300], [key])
    try:
        size = len(resp.json()["data"][0]["embedding"])
    except (ValueError, KeyError, IndexError, TypeError):
        return _fail(200, resp.text[:300], [key], message="服務商回應的格式不是 embeddings")
    return _ok(f"向量模型 {model} 可用（{size} 維，取前 {dim} 維）")


async def _get(url: str, headers: Dict[str, str], secrets: List[str]):
    from app.network import public_http_client
    try:
        async with public_http_client(timeout=TIMEOUT) as client:
            return await client.get(url, headers=headers), None
    except Exception as exc:
        return None, _fail(None, f"{type(exc).__name__}: {exc}", secrets)


async def _check_gemini(values: Dict[str, Any]) -> Dict[str, Any]:
    raw = _candidate(values, "GEMINI_API_KEYS")
    keys = [k for k in str(raw).split(",") if k]
    if not keys:
        return _fail(None, message="還沒有設定 Gemini API 金鑰")
    good, last_failure = 0, None
    for key in keys[:10]:
        resp, failure = await _get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                                   {"x-goog-api-key": key}, keys)
        if resp is not None and resp.status_code == 200:
            good += 1
        else:
            last_failure = failure or _fail(resp.status_code, resp.text[:300], keys)
    if good == len(keys[:10]):
        return _ok(f"{good} 把 Gemini 金鑰都有效")
    if good:
        return {**last_failure, "message": f"{len(keys[:10])} 把裡有 {good} 把有效；其餘：{last_failure['message']}"}
    return last_failure


async def _check_telegram(values: Dict[str, Any]) -> Dict[str, Any]:
    token = _candidate(values, "TELEGRAM_BOT_TOKEN")
    if not token:
        return _fail(None, message="還沒有設定 Bot Token")
    resp, failure = await _get(f"https://api.telegram.org/bot{token}/getMe", {}, [token])
    if failure:
        return failure
    if resp.status_code != 200:
        return _fail(resp.status_code, resp.text[:300], [token],
                     message="Bot Token 無效" if resp.status_code in (401, 404) else "")
    username = (resp.json().get("result") or {}).get("username", "")
    return _ok(f"Bot 正常：@{username}")


async def _check_line(values: Dict[str, Any]) -> Dict[str, Any]:
    token = _candidate(values, "LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        return _fail(None, message="還沒有設定 Channel Access Token")
    resp, failure = await _get("https://api.line.me/v2/bot/info", {"Authorization": f"Bearer {token}"}, [token])
    if failure:
        return failure
    if resp.status_code != 200:
        return _fail(resp.status_code, resp.text[:300], [token])
    return _ok(f"LINE Bot 正常：{resp.json().get('displayName', '')}")


async def _check_github(values: Dict[str, Any]) -> Dict[str, Any]:
    token = _candidate(values, "GITHUB_TOKEN")
    if not token:
        return _fail(None, message="還沒有設定 GitHub Token")
    resp, failure = await _get("https://api.github.com/user", {
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": "OmniKeep"}, [token])
    if failure:
        return failure
    if resp.status_code != 200:
        return _fail(resp.status_code, resp.text[:300], [token])
    return _ok(f"GitHub Token 有效：{resp.json().get('login', '')}")


CHECKS: Dict[str, Callable] = {
    "llm": _check_llm,
    "embeddings": _check_embeddings,
    "gemini": _check_gemini,
    "telegram": _check_telegram,
    "line": _check_line,
    "github": _check_github,
}


async def run_check(service: str, values: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return await CHECKS[service](values)
    except ValueError as exc:  # a typed value did not validate
        return _fail(None, message=str(exc))
    except Exception as exc:
        return _fail(None, f"{type(exc).__name__}: {exc}", message="測試時發生錯誤")
