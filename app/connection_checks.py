"""Try a provider or bot credential from the settings page, before or after saving it.

Values typed in the form are tested as typed; fields left out fall back to
what is in effect now (a credential sent as "" means "test without a key").
Nothing here changes settings or the service status.
"""
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from openai import APIConnectionError, APIStatusError, AsyncOpenAI

from app import app_settings
from app.ai_status import redact
from app.config import settings
from app.error_translate import translate

TIMEOUT = 20.0
JSON_TIMEOUT = 60.0  # a free tier can take tens of seconds for one answer
GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
JSON_SYSTEM = "你是連線測試助手。只輸出一個 JSON 物件，不要有其他文字。"
JSON_PROMPT = '請用繁體中文回覆這個 JSON 物件，值照抄：{"回覆": "連線成功", "數字": 42}'


def _candidate(values: Dict[str, Any], key: str) -> Any:
    spec = app_settings.SPEC_BY_KEY[key]
    raw = values.get(key)
    if raw not in (None, ""):
        return app_settings.normalize(spec, raw)
    if spec.secret and raw == "":
        return ""  # sent empty on purpose: test without any key (a local server)
    return getattr(settings, spec.field)


def _explain(status: Optional[int], detail: str = "") -> str:
    if detail:
        info = translate(status, detail)
        if info["kind"] not in ("auth", "not_found", "rate_limit", "server", "connection", "bad_request", "other"):
            return info["hint"]  # a specific diagnosis (disabled key, empty balance, …)
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
    detail = _scrub(detail, secrets or [])
    info = translate(status, detail)
    return {"ok": False, "status": status, "message": message or _explain(status, detail),
            "detail": detail, "hint": info["hint"], "action_required": info["action_required"],
            "fix_url": info["fix_url"]}


def _guard_base_url(values: Dict[str, Any], base_url: str) -> Optional[Dict[str, Any]]:
    """Never send the saved key to an address it was not saved for."""
    moved = base_url.rstrip("/") != settings.OPENAI_BASE_URL.rstrip("/")
    if moved and settings.OPENAI_API_KEY and "OPENAI_API_KEY" not in values:
        return _fail(None, message="更換 API 位址時，請一併輸入要測試的 API 金鑰")
    return None


def _parse_json_reply(text: str) -> Optional[Dict[str, Any]]:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text or "").strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        text = match.group(1)
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start:end + 1])
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


async def check_chat(base_url: str, key: str, model: str, secrets: Optional[List[str]] = None,
                     json_mode: bool = True, extra_body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """List the models, then send one small Chinese json_object request and parse the answer.

    `extra_body` (a connection's caps["extra_body"]) goes into the request exactly as
    the analysis calls send it, so a reasoning switch is tested too.

    Returns the usual {ok, status, message, detail} plus `models` (what the
    endpoint lists), `json_mode` (whether response_format json_object worked)
    and `latency_ms` of the JSON request.
    """
    from app.providers.openai_compatible import ProviderUnavailableError, client_auth, extract_completion_content
    secrets = [key, *(secrets or [])]
    client = AsyncOpenAI(base_url=base_url, timeout=JSON_TIMEOUT, max_retries=0, **client_auth(key))
    listed: List[str] = []
    extra: Dict[str, Any] = {"models": [], "json_mode": None, "latency_ms": None}
    try:
        try:
            page = await client.models.list()
            listed = [str(m.id).removeprefix("models/") for m in page.data]
            extra["models"] = listed[:300]
        except APIStatusError as exc:
            if exc.status_code in (401, 403):
                return {**_fail(exc.status_code, str(exc), secrets), **extra}
            # Some compatible servers do not list models; the request below settles it.
        except APIConnectionError:
            raise
        except Exception:
            pass
        messages = [{"role": "system", "content": JSON_SYSTEM}, {"role": "user", "content": JSON_PROMPT}]
        more = {"extra_body": dict(extra_body)} if extra_body else {}
        started = time.monotonic()
        used_json_mode = json_mode
        try:
            if not json_mode:
                raise _NoJsonMode()
            response = await client.chat.completions.create(
                model=model, messages=messages, temperature=0, response_format={"type": "json_object"}, **more)
        except (_NoJsonMode, APIStatusError) as exc:
            if isinstance(exc, APIStatusError) and exc.status_code != 400:
                raise
            used_json_mode = False  # response_format refused: plain request, then parse
            response = await client.chat.completions.create(model=model, messages=messages, temperature=0, **more)
        extra["latency_ms"] = int((time.monotonic() - started) * 1000)
        extra["json_mode"] = used_json_mode
        try:
            text = extract_completion_content(response)
        except ProviderUnavailableError as exc:
            return {**_fail(200, str(exc), secrets, message=str(exc)), **extra}
        except ValueError as exc:
            return {**_fail(200, str(exc), secrets, message="服務商回應的格式不是 chat completion"), **extra}
        parsed = _parse_json_reply(text)
        if parsed is None:
            return {**_fail(200, (text or "")[:300], secrets,
                            message=f"模型 {model} 有回應，但不是可以解析的 JSON：換一個模型通常就能解決"), **extra}
        seconds = extra["latency_ms"] / 1000
        note = "" if used_json_mode or not json_mode else "；這個模型不支援 JSON 格式參數，會改用一般請求再解析"
        found = f"（服務商列出 {len(listed)} 個模型）" if listed else ""
        return {**_ok(f"連線成功：模型 {model} 回了可解析的中文 JSON，花了 {seconds:.1f} 秒{note}{found}"), **extra}
    except APIStatusError as exc:
        return {**_fail(exc.status_code, str(exc), secrets), **extra}
    except APIConnectionError as exc:
        return {**_fail(None, f"{type(exc).__name__}: {exc}", secrets), **extra}
    finally:
        await client.close()


class _NoJsonMode(Exception):
    pass


async def check_vertex(key: str, model: str, secrets: Optional[List[str]] = None) -> Dict[str, Any]:
    """The Vertex AI (Agent Platform) express-mode version of check_chat: one small Chinese
    JSON request through google-genai, the way GeminiProvider calls it."""
    from google.genai import types as gtypes
    from app.providers.gemini import genai_client
    secrets = [key, *(secrets or [])]
    extra: Dict[str, Any] = {"models": [], "json_mode": True, "latency_ms": None}
    started = time.monotonic()
    try:
        client = genai_client(key, vertexai=True)
        response = await client.aio.models.generate_content(
            model=model, contents=[JSON_PROMPT],
            config=gtypes.GenerateContentConfig(system_instruction=JSON_SYSTEM, temperature=0,
                                                response_mime_type="application/json"))
    except Exception as exc:
        code = getattr(exc, "code", None)
        return {**_fail(code if isinstance(code, int) else None, f"{type(exc).__name__}: {exc}", secrets), **extra}
    extra["latency_ms"] = int((time.monotonic() - started) * 1000)
    text = getattr(response, "text", None) or ""
    if _parse_json_reply(text) is None:
        return {**_fail(200, text[:300], secrets,
                        message=f"模型 {model} 有回應，但不是可以解析的 JSON：換一個模型通常就能解決"), **extra}
    return {**_ok(f"連線成功（Vertex AI）：模型 {model} 回了可解析的中文 JSON，花了 {extra['latency_ms'] / 1000:.1f} 秒"),
            **extra}


async def _check_llm(values: Dict[str, Any]) -> Dict[str, Any]:
    base_url = _candidate(values, "OPENAI_BASE_URL")
    blocked = _guard_base_url(values, base_url)
    if blocked:
        return blocked
    key = _candidate(values, "OPENAI_API_KEY")
    model = _candidate(values, "PRIMARY_MODEL")
    if not key:
        if "api.openai.com" in base_url:
            return _fail(None, message="還沒有設定 API 金鑰")
        # Local servers such as Ollama take any key; the provider sends the same placeholder.
        key = "dummy-key"
    return await check_chat(base_url, key, model)


async def check_connection(conn, model: Optional[str] = None, purpose: str = "chat") -> Dict[str, Any]:
    """Test a saved (or typed, unsaved) connection from 設定 › AI 服務商.

    `conn` needs kind, base_url, key, model and caps (app.ai_connections.Connection
    or anything shaped like it). purpose "embeddings" tests the vector endpoint instead.
    """
    model = model or conn.model
    if conn.kind == "gemini":
        keys = [k for k in (conn.key or "").split(",") if k]
        if not keys:
            return _fail(None, message="還沒有設定 Gemini API 金鑰")
        if purpose == "embeddings":
            return _fail(None, message="Gemini 目前不能用在向量")
        if conn.caps.get("vertex"):
            result = await check_vertex(keys[0], model, secrets=keys)
        else:
            result = await check_chat(GEMINI_OPENAI_URL, keys[0], model, secrets=keys,
                                      json_mode=conn.caps.get("json_mode", True) is not False)
        if result["ok"] and len(keys) > 1:
            result["message"] += f"（用第 1 把測試，共 {len(keys)} 把會輪流使用）"
        return result
    base_url = (conn.base_url or "").rstrip("/")
    if not base_url:
        return _fail(None, message="還沒有填 API 位址")
    if purpose == "embeddings":
        return await _check_connection_embeddings(conn, model)
    if conn.kind == "ollama":
        base_url += "/v1"
    from app.ai_connections import extra_body_for
    return await check_chat(base_url, conn.key or "dummy-key", model,
                            json_mode=conn.caps.get("json_mode", True) is not False,
                            extra_body=extra_body_for(conn, model))


async def _check_connection_embeddings(conn, model: str) -> Dict[str, Any]:
    dim = int(settings.EMBEDDING_DIM)
    base_url = conn.base_url.rstrip("/")
    if conn.kind == "ollama":
        try:
            resp = await _ollama("POST", f"{base_url}/api/embed", json={"model": model, "input": "測試"})
        except Exception as exc:
            return _fail(None, f"{type(exc).__name__}: {exc}", message=f"連不上 {base_url}，Ollama 是否已啟動？")
        if resp.status_code == 404:
            return _fail(404, resp.text[:300], message=f"Ollama 找不到模型 {model}，請先執行 ollama pull {model}")
        if resp.status_code != 200:
            return _fail(resp.status_code, resp.text[:300])
        try:
            size = len((resp.json().get("embeddings") or [[]])[0])
        except (ValueError, IndexError, TypeError, AttributeError):
            size = 0
    else:
        from app.network import UnsafeURL, public_http_client
        secrets = [conn.key] if conn.key else []
        try:
            async with public_http_client(timeout=TIMEOUT) as client:
                resp = await client.post(f"{base_url}/embeddings",
                                         headers={"Authorization": f"Bearer {conn.key or 'dummy-key'}"},
                                         json={"input": "測試", "model": model, "dimensions": dim})
        except UnsafeURL:
            return _fail(None, message="雲端向量只能用公開網址；本機的向量服務請用 Ollama 卡片")
        except Exception as exc:
            return _fail(None, f"{type(exc).__name__}: {exc}", secrets)
        if resp.status_code != 200:
            return _fail(resp.status_code, resp.text[:300], secrets)
        try:
            size = len(resp.json()["data"][0]["embedding"])
        except (ValueError, KeyError, IndexError, TypeError):
            return _fail(200, resp.text[:300], secrets, message="服務商回應的格式不是 embeddings")
    if size < dim:
        return _fail(200, "", message=f"{model} 回傳 {size} 維，少於需要的 {dim} 維")
    return _ok(f"向量模型 {model} 可用（{size} 維，取前 {dim} 維）")


async def _check_embeddings(values: Dict[str, Any]) -> Dict[str, Any]:
    from app.network import UnsafeURL, public_http_client
    base_url = _candidate(values, "OPENAI_BASE_URL")
    blocked = _guard_base_url(values, base_url)
    if blocked:
        return blocked
    key = _candidate(values, "OPENAI_API_KEY")
    model = _candidate(values, "EMBEDDING_MODEL")
    # Same substitution as app.vector.remote_embedding_model(): the Ollama-only
    # model is replaced by OpenAI's when the cloud endpoint is used.
    model = "text-embedding-3-small" if model == "embeddinggemma-2" else model
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
        return _fail(None, message="還沒有設定機器人權杖")
    resp, failure = await _get(f"https://api.telegram.org/bot{token}/getMe", {}, [token])
    if failure:
        return failure
    if resp.status_code != 200:
        return _fail(resp.status_code, resp.text[:300], [token],
                     message="機器人權杖無效" if resp.status_code in (401, 404) else "")
    username = (resp.json().get("result") or {}).get("username", "")
    return _ok(f"機器人正常：@{username}")


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


async def _ollama(method: str, url: str, **kwargs):
    """The operator's own local runner: plain httpx, like app.vector and app.brain."""
    import httpx
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
        return await client.request(method, url, **kwargs)


async def _check_ollama(values: Dict[str, Any]) -> Dict[str, Any]:
    base_url = str(_candidate(values, "OLLAMA_BASE_URL")).rstrip("/")
    model = _candidate(values, "EMBEDDING_MODEL")
    if not base_url:
        return _fail(None, message="Ollama 位址是空的：向量會改用 OpenAI 相容服務或本機雜湊")
    try:
        resp = await _ollama("POST", f"{base_url}/api/embed", json={"model": model, "input": "ping"})
    except Exception as exc:
        return _fail(None, f"{type(exc).__name__}: {exc}", message=f"連不上 {base_url}，Ollama 是否已啟動？")
    if resp.status_code == 404:
        return _fail(404, resp.text[:300], message=f"Ollama 找不到模型 {model}，請先執行 ollama pull {model}")
    if resp.status_code != 200:
        return _fail(resp.status_code, resp.text[:300])
    try:
        size = len((resp.json().get("embeddings") or [[]])[0])
    except (ValueError, IndexError, TypeError, AttributeError):
        size = 0
    dim = int(settings.EMBEDDING_DIM)
    if size < dim:
        return _fail(200, resp.text[:300], message=f"{model} 回傳 {size} 維，少於需要的 {dim} 維")
    return _ok(f"Ollama 向量模型 {model} 可用（{size} 維，取前 {dim} 維）")


async def _check_brain(values: Dict[str, Any]) -> Dict[str, Any]:
    provider = _candidate(values, "BRAIN_PROVIDER")
    if provider not in ("ollama", "strata"):
        return _ok("提問直接使用分析的 AI 連線，請到「設定 › AI」測試那條連線")
    base_url = str(_candidate(values, "BRAIN_BASE_URL")).rstrip("/")
    model = _candidate(values, "BRAIN_MODEL")
    try:
        resp = await _ollama("GET", f"{base_url}/api/tags")
    except Exception as exc:
        return _fail(None, f"{type(exc).__name__}: {exc}",
                     message=f"連不上 {base_url}，Ollama 是否已啟動？（連不上時會改用主要服務商回答）")
    if resp.status_code != 200:
        return _fail(resp.status_code, resp.text[:300])
    names = [m.get("name", "") for m in resp.json().get("models", [])]
    if model in names or f"{model}:latest" in names:
        return _ok(f"Ollama 正常，找到模型 {model}")
    return _fail(404, "、".join(names)[:300], message=f"Ollama 沒有模型 {model}，請先執行 ollama pull {model}")


CHECKS: Dict[str, Callable] = {
    "llm": _check_llm,
    "embeddings": _check_embeddings,
    "ollama": _check_ollama,
    "brain": _check_brain,
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
