"""A local OpenAI-compatible endpoint that answers with OmniKeep's Vertex AI connections.

Other programs on this computer (claude-mem first) send /v1/chat/completions here instead of
holding a Google key themselves: the keys stay encrypted in omnikeep.db and are decrypted only
in this process's memory, and the calls are paid from the GCP credits of the Vertex projects.

Run by run_gateway.py (started and kept alive by scripts/watchdog.ps1 when llm_gateway.json
exists next to the database). It listens on 127.0.0.1 only.

Order (llm_gateway.json, read again whenever the file changes, so no restart is needed):
  for each connection in "connections":       c15, then c16
      for each model in "models":             gemini-4-hydrogen, then gemini-3.8-flash
  A rate limit (429), a refused key or a spend cap (401/403) or an empty balance moves on to the
  next connection at once, since the other model is billed to the same project; the models left
  untried on a rate-limited connection are tried at the end, after every connection had its turn.
  Anything else (a model gone, 5xx, an empty answer) tries the next model on the same connection.
  A connection that was rate limited or refused a moment ago goes to the back of the line.
Thinking is always "high": a lower level in the file is raised to it (owner's rule, 2026-11-18).
A connection past its spend cap (or out of balance) is left out for QUOTA_COOLDOWN (6 hours) and
then tried once more at the back; the other refusals only go to the back of the line.

Budget per source ("sources" in llm_gateway.json, checked before anything is sent):
  "sources": {"claude-mem": {"daily_requests": 400, "daily_tokens": 5000000, "until": "2026-12-03"},
              "*": {...}}   (for the sources not named; without it DEFAULT_SOURCE_LIMITS apply)
  daily_requests / daily_tokens  answered calls and prompt+completion tokens today (local time),
                                 counted in ai_usage_sources; null means no cap. Over it: 429
                                 with Retry-After until midnight.
  until                          the end date: from 00:00 (local time) of that day the source is
                                 refused with 403 ("2026-12-03"; an ISO time with its offset is
                                 taken as is). A value that cannot be read refuses the source.
  The owner is told once (app/owner_alert.py): the first refusal of the day over a cap, the first
  refusal after the end date.

Callers are told apart by their token (Authorization: Bearer ...), one per source, kept
encrypted in app_settings as "_gateway.token.<source>". Every attempt is counted in ai_usage
(per connection, as OmniKeep's own calls are) and in ai_usage_sources (per source and model).
"""
import asyncio
import hmac
import json
import logging
import re
import secrets
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings

logger = logging.getLogger("omnikeep.llm_gateway")

CONFIG_NAME = "llm_gateway.json"
TOKEN_PREFIX = "_gateway.token."
HOST = "127.0.0.1"
DEFAULT_CONFIG: Dict[str, Any] = {
    "port": 5101,
    # 2026-11-18: c15's credits expire on 2026-12-03, c16's in 2027: use c15's first.
    "connections": [15, 16],
    "models": ["gemini-4-hydrogen", "gemini-3.8-flash"],
    "thinking_level": "high",
    # claude-mem gives up on a streamed answer after 300 s; stop trying before that.
    "deadline_seconds": 280,
    "sources": {},
}
# A source with no entry of its own and no "*" entry: about the median day of claude-mem's use
# on 2026-11-19..23 (369 answered calls, 4.7M tokens); the busiest day was 663 and 8.9M.
DEFAULT_SOURCE_LIMITS: Dict[str, Any] = {"daily_requests": 400, "daily_tokens": 5_000_000, "until": None}
LIMIT_FIELDS = ("daily_requests", "daily_tokens")
THINKING_LEVELS = ("high",)  # google-genai's ThinkingLevel has nothing above HIGH
ACCOUNT_KINDS = ("rate_limit", "auth", "disabled", "quota")  # the whole project, not one model
REFUSED_COOLDOWN = 600.0
QUOTA_COOLDOWN = 6 * 3600.0  # a spend cap does not lift by itself within minutes
RATE_LIMIT_COOLDOWN = 60.0
KEEPALIVE_SECONDS = 15.0
_SOURCE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


# ── Configuration ───────────────────────────────────────────────

def config_path() -> Path:
    return Path(settings.DATABASE_PATH).resolve().parent / CONFIG_NAME


_config_cache: Dict[str, Any] = {}


def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    """llm_gateway.json over DEFAULT_CONFIG, checked; cached until the file changes."""
    path = Path(path) if path else config_path()
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        stamp = None
    cached = _config_cache.get(str(path))
    if cached and cached[0] == stamp:
        return cached[1]
    raw: Dict[str, Any] = {}
    if stamp is not None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig")) or {}
        except (OSError, ValueError) as exc:
            logger.warning("%s cannot be read (%s); keeping the previous order", path.name, exc)
            return cached[1] if cached else dict(DEFAULT_CONFIG)
    config = check_config(raw)
    _config_cache[str(path)] = (stamp, config)
    return config


def check_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        if key in raw:
            config[key] = raw[key]
    try:
        config["connections"] = [int(c) for c in config["connections"]]
    except (TypeError, ValueError):
        logger.warning("llm_gateway.json: connections must be connection ids; using %s", DEFAULT_CONFIG["connections"])
        config["connections"] = list(DEFAULT_CONFIG["connections"])
    models = [str(m).strip() for m in (config["models"] or []) if str(m).strip()]
    config["models"] = models or list(DEFAULT_CONFIG["models"])
    level = str(config.get("thinking_level") or "").lower()
    if level not in THINKING_LEVELS:
        logger.warning("llm_gateway.json: thinking_level %r is below the owner's minimum; using high", level)
        level = "high"
    config["thinking_level"] = level
    try:
        config["port"] = int(config["port"])
        config["deadline_seconds"] = max(10.0, float(config["deadline_seconds"]))
    except (TypeError, ValueError):
        config["port"], config["deadline_seconds"] = DEFAULT_CONFIG["port"], DEFAULT_CONFIG["deadline_seconds"]
    config["sources"] = _check_sources(config.get("sources"))
    return config


def _parse_until(value: Any) -> datetime:
    """The moment a source stops being served; a bare date means 00:00 local time that day."""
    text = str(value).strip()
    if len(text) == 10:
        return datetime.strptime(text, "%Y-%m-%d").astimezone()  # naive -> this computer's time zone
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.astimezone()


def _check_sources(raw: Any) -> Dict[str, Dict[str, Any]]:
    """source -> {daily_requests, daily_tokens, until, broken}; an unreadable entry refuses its source."""
    if raw in (None, ""):
        return {}
    if not isinstance(raw, dict):
        logger.warning("llm_gateway.json: sources must be an object; every source is refused until it is fixed")
        return {"*": {**DEFAULT_SOURCE_LIMITS, "broken": "sources is not an object"}}
    out: Dict[str, Dict[str, Any]] = {}
    for name, entry in raw.items():
        limits: Dict[str, Any] = {**DEFAULT_SOURCE_LIMITS, "broken": ""}
        if not isinstance(entry, dict):
            limits["broken"] = "not an object"
        else:
            for field_name in LIMIT_FIELDS:
                if field_name not in entry:
                    continue
                value = entry[field_name]
                if value is None:
                    limits[field_name] = None
                elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    limits[field_name] = value
                else:
                    limits["broken"] = f"{field_name} {value!r} is not a whole number"
            if entry.get("until") not in (None, ""):
                try:
                    limits["until"] = _parse_until(entry["until"])
                except (TypeError, ValueError):
                    limits["broken"] = f"until {entry['until']!r} is not a date"
        if limits["broken"]:
            logger.warning("llm_gateway.json: sources.%s: %s; this source is refused until it is fixed",
                           name, limits["broken"])
        out[str(name)] = limits
    return out


def limits_for(source: str, config: Dict[str, Any]) -> Dict[str, Any]:
    sources = config.get("sources") or {}
    return sources.get(source) or sources.get("*") or {**DEFAULT_SOURCE_LIMITS, "broken": ""}


def write_default_config(path: Optional[Path] = None) -> Path:
    """Create llm_gateway.json when it is missing (it switches the gateway on for the watchdog)."""
    path = Path(path) if path else config_path()
    if not path.exists():
        note = ("Order of the local OpenAI-compatible endpoint (app/llm_gateway.py). Connection ids are "
                "ai_connections rows (Vertex only). Edits apply without a restart.")
        path.write_text(json.dumps({"_note": note, **DEFAULT_CONFIG}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return path


# ── Tokens ──────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_token(source: str) -> str:
    """The token `source` calls with, created (random, stored encrypted) on first use."""
    from app import secret_box
    from app.database import get_db_connection
    if not _SOURCE.match(source or ""):
        raise ValueError("source: lowercase letters, digits, - and _ only")
    key = TOKEN_PREFIX + source
    with closing(get_db_connection()) as db, db:
        row = db.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        if row:
            return secret_box.decrypt(row["value"])
        token = "okgw-" + secrets.token_urlsafe(32)
        db.execute("INSERT INTO app_settings (key, value, is_secret, updated_at) VALUES (?, ?, 1, ?)",
                   (key, secret_box.encrypt(token), _now()))
        db.execute("INSERT INTO app_settings_audit (key, action, created_at) VALUES (?, 'set', ?)", (key, _now()))
        return token


def tokens() -> Dict[str, str]:
    """source -> token, for every source that has one."""
    from app import secret_box
    from app.database import get_db_connection
    out: Dict[str, str] = {}
    with closing(get_db_connection()) as db:
        rows = db.execute("SELECT key, value FROM app_settings WHERE key LIKE ? AND is_secret = 1",
                          (TOKEN_PREFIX + "%",)).fetchall()
    for row in rows:
        try:
            out[row["key"][len(TOKEN_PREFIX):]] = secret_box.decrypt(row["value"])
        except secret_box.SecretUnavailable:
            logger.warning("Gateway token %s cannot be decrypted with the current master key", row["key"])
    return out


def source_for(authorization: str) -> Optional[str]:
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not presented.strip():
        return None
    presented = presented.strip()
    for source, token in tokens().items():
        if hmac.compare_digest(presented.encode(), token.encode()):
            return source
    return None


# ── Budget per source ───────────────────────────────────────────

class GatewayError(Exception):
    def __init__(self, status: int, message: str, attempts: List[str], retry_after: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.attempts = attempts
        self.retry_after = retry_after


def usage_today(source: str) -> Dict[str, int]:
    """Answered calls and tokens for `source` today (local time), every connection and model."""
    from app import ai_usage
    today = datetime.now().astimezone().date().isoformat()
    rows = [r for r in ai_usage.source_rows(source, since=today) if r["day"] == today]
    return {"requests": sum(r["requests"] for r in rows),
            "tokens": sum(r["prompt_tokens"] + r["completion_tokens"] for r in rows)}


def _seconds_to_midnight(now: datetime) -> int:
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((tomorrow - now).total_seconds()))


def check_source(source: str, config: Dict[str, Any], now: Optional[datetime] = None) -> None:
    """Raise GatewayError when `source` may not be served now (llm_gateway.json "sources")."""
    from app import owner_alert
    limits = limits_for(source, config)
    if limits.get("broken"):
        raise GatewayError(403, f"Source {source} is refused: its llm_gateway.json sources entry "
                                f"cannot be read ({limits['broken']})", [])
    now = (now or datetime.now()).astimezone()
    until = limits.get("until")
    if until is not None and now >= until:
        owner_alert.alert_once(
            f"gateway.until.{source}.{until.date().isoformat()}", f"⛔ AI 轉接端點已停止服務 {source}",
            f"llm_gateway.json 設定 {source} 用到 {until:%Y-%m-%d %H:%M} 為止，之後的請求一律拒絕，"
            f"不會再花到付費額度。要繼續用就把 sources.{source}.until 改到新的日期。")
        raise GatewayError(403, f"Source {source} is not served from {until.isoformat()} on "
                                f"(llm_gateway.json sources.{source}.until)", [])
    caps = {name: limits[name] for name in LIMIT_FIELDS if limits.get(name) is not None}
    if not caps:
        return
    used = usage_today(source)
    for name, cap in caps.items():
        spent = used["requests" if name == "daily_requests" else "tokens"]
        if spent >= cap:
            what = " 次請求" if name == "daily_requests" else " tokens"
            owner_alert.alert_once(
                f"gateway.cap.{source}.{now.date().isoformat()}", f"⏸️ {source} 今天的 AI 用量到上限了",
                f"{source} 今天已用 {spent:,}{what}（上限 {cap:,}），今天其餘的請求一律拒絕，明天 00:00 自動恢復。"
                f"要調整就改 llm_gateway.json 的 sources.{source}.{name}。")
            raise GatewayError(429, f"Source {source} reached its daily cap ({name} {spent}/{cap}); "
                                    f"it resets at midnight", [], retry_after=_seconds_to_midnight(now))


# ── Calling Vertex ──────────────────────────────────────────────


@dataclass
class Result:
    text: str
    connection: str
    model: str
    thinking_level: str
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    thoughts_tokens: int
    attempts: List[str] = field(default_factory=list)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("text", "input_text"):
                parts.append(str(part.get("text") or ""))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return "" if content is None else str(content)


def to_gemini(messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """(system instruction, contents) from OpenAI chat messages; same-role turns are merged."""
    system: List[str] = []
    contents: List[Dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        text = _content_text(message.get("content"))
        if role in ("system", "developer"):
            if text:
                system.append(text)
            continue
        gemini_role = "model" if role == "assistant" else "user"
        if not text:
            continue
        if contents and contents[-1]["role"] == gemini_role:
            contents[-1]["parts"][0]["text"] += "\n\n" + text
        else:
            contents.append({"role": gemini_role, "parts": [{"text": text}]})
    if not contents:
        raise GatewayError(400, "messages has no user or assistant text", [])
    return "\n\n".join(system), contents


_FINISH = {"STOP": "stop", "MAX_TOKENS": "length", "SAFETY": "content_filter", "RECITATION": "content_filter",
           "PROHIBITED_CONTENT": "content_filter", "BLOCKLIST": "content_filter", "SPII": "content_filter"}


def _finish_reason(response: Any) -> str:
    try:
        reason = response.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return "stop"
    name = getattr(reason, "name", None) or str(reason or "STOP")
    return _FINISH.get(name.split(".")[-1], "stop")


def _thoughts(response: Any) -> int:
    meta = getattr(response, "usage_metadata", None)
    try:
        return max(int(getattr(meta, "thoughts_token_count", 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


async def _call(conn, model: str, system: str, contents, config: Dict[str, Any], options: Dict[str, Any]):
    """One request to one connection and model; ai_status and ai_usage are recorded inside."""
    from google.genai import types as gtypes
    from app.providers import limiter_for
    from app.providers.gemini import _generate_content, genai_client
    key = next((k for k in conn.key.split(",") if k), "")
    kwargs: Dict[str, Any] = {"thinking_config": gtypes.ThinkingConfig(thinking_level=config["thinking_level"])}
    if system:
        kwargs["system_instruction"] = system
    if options.get("temperature") is not None:
        kwargs["temperature"] = options["temperature"]
    if options.get("json"):
        kwargs["response_mime_type"] = "application/json"
    return await _generate_content(genai_client(key, vertexai=True), conn.status_key, conn.label, limiter_for(conn),
                                   model=model, contents=contents, config=gtypes.GenerateContentConfig(**kwargs))


def _connections(ids: List[int]) -> List[Any]:
    from app import ai_connections, ai_status
    found = []
    for connection_id in ids:
        conn = ai_connections.get_connection(connection_id)
        if conn is None or not conn.enabled or conn.kind != "gemini" or not conn.caps.get("vertex"):
            logger.warning("Gateway: connection c%s is missing, switched off or not Vertex AI; skipped", connection_id)
            continue
        if conn.key_broken or not conn.key:
            logger.warning("Gateway: connection c%s has no readable key; skipped", connection_id)
            continue
        found.append(conn)
    # Past its spend cap within QUOTA_COOLDOWN: left out, every call would only be refused again.
    found = [c for c in found if not _quota_hold(c.status_key)]
    # A connection that was rate limited or refused a moment ago waits behind the others.
    return [c for c in found if not ai_status.unusable(c.status_key)] + \
           [c for c in found if ai_status.unusable(c.status_key)]


QUOTA_REASON = "支出上限或額度用完"


def _quota_hold(status_key: str) -> bool:
    from app import ai_status
    entry = ai_status.get(status_key)
    return entry.get("cooldown_reason") == QUOTA_REASON and entry.get("cooldown_until", 0.0) > time.time()


def _short(exc: BaseException) -> str:
    from app.ai_status import redact
    return redact(" ".join(f"{type(exc).__name__}: {exc}".split()))[:200]


async def complete(messages: List[Dict[str, Any]], source: str, options: Optional[Dict[str, Any]] = None,
                   config: Optional[Dict[str, Any]] = None, caller=None) -> Result:
    """Answer `messages` with the first connection and model that can (order: module docstring)."""
    from app import ai_status, ai_usage
    from app.error_translate import classify
    from app.providers.base import EmptyResponseError
    from app.providers.chain import _retry_after
    options = options or {}
    config = config or load_config()
    caller = caller or _call
    check_source(source, config)
    system, contents = to_gemini(messages)
    conns = _connections(config["connections"])
    if not conns:
        raise GatewayError(503, "No usable Vertex AI connection in llm_gateway.json "
                                "(switched off, or past its spend cap within the last 6 hours)", [])
    deadline = time.monotonic() + config["deadline_seconds"]
    attempts: List[str] = []
    later: List[Tuple[Any, str]] = []  # models skipped on a rate-limited connection
    rate_limited = False

    async def attempt(conn, model) -> Tuple[Optional[Result], Optional[str]]:
        """(result, None) on success, else (None, the failure's kind)."""
        nonlocal rate_limited
        left = deadline - time.monotonic()
        if left <= 1:
            attempts.append(f"{conn.status_key}/{model}:deadline")
            return None, "deadline"
        try:
            response = await asyncio.wait_for(caller(conn, model, system, contents, config, options), left)
            text = response.text or ""
            if not text.strip():
                raise EmptyResponseError(conn.label)
        except asyncio.TimeoutError:
            attempts.append(f"{conn.status_key}/{model}:timeout")
            ai_usage.record_source(conn.status_key, source, model, False)
            return None, "deadline"
        except Exception as exc:  # noqa: BLE001 - any failure of one call is classified and the next one tried
            info = classify(exc)
            attempts.append(f"{conn.status_key}/{model}:{info['status'] or info['kind']}")
            ai_usage.record_source(conn.status_key, source, model, False)
            logger.warning("Gateway [%s] %s %s failed (%s: %s)", source, conn.status_key, model, info["kind"],
                           _short(exc))
            if info["kind"] == "rate_limit":
                rate_limited = True
                ai_status.set_cooldown(conn.status_key, _retry_after(exc) or RATE_LIMIT_COOLDOWN, "限流")
            elif info["kind"] == "quota":
                ai_status.set_cooldown(conn.status_key, QUOTA_COOLDOWN, QUOTA_REASON)
            elif info["kind"] in ACCOUNT_KINDS:
                ai_status.set_cooldown(conn.status_key, REFUSED_COOLDOWN, "被拒絕（金鑰、權限或支出上限）")
            return None, info["kind"]
        ai_usage.record_source(conn.status_key, source, model, True, response)
        prompt, completion = ai_usage.token_counts(response)
        attempts.append(f"{conn.status_key}/{model}:ok")
        return Result(text=text, connection=conn.status_key, model=model, thinking_level=config["thinking_level"],
                      finish_reason=_finish_reason(response), prompt_tokens=prompt, completion_tokens=completion,
                      thoughts_tokens=_thoughts(response), attempts=attempts), None

    for conn in conns:
        for index, model in enumerate(config["models"]):
            result, kind = await attempt(conn, model)
            if result:
                return result
            if kind == "deadline":
                raise GatewayError(504, "No answer before the deadline", attempts)
            if kind == "rate_limit":
                later += [(conn, m) for m in config["models"][index + 1:]]
            if kind in ACCOUNT_KINDS:
                break
    for conn, model in later:
        result, kind = await attempt(conn, model)
        if result:
            return result
        if kind == "deadline":
            break
    if rate_limited:
        raise GatewayError(429, "Every Vertex AI connection is rate limited", attempts)
    raise GatewayError(502, "Every Vertex AI connection failed", attempts)


# ── HTTP ────────────────────────────────────────────────────────

def _usage(result: Result) -> Dict[str, Any]:
    return {"prompt_tokens": result.prompt_tokens, "completion_tokens": result.completion_tokens,
            "total_tokens": result.prompt_tokens + result.completion_tokens,
            "completion_tokens_details": {"reasoning_tokens": result.thoughts_tokens}}


def _error_body(status: int, message: str) -> Dict[str, Any]:
    kind = {401: "authentication_error", 400: "invalid_request_error", 403: "permission_error",
            429: "rate_limit_error"}.get(status, "api_error")
    return {"error": {"message": message, "type": kind, "code": status}}


def _error_headers(exc: GatewayError) -> Dict[str, str]:
    headers = {"x-omnikeep-attempts": ",".join(exc.attempts)}
    if exc.retry_after:
        headers["retry-after"] = str(exc.retry_after)
    return headers


def _log_result(source: str, result: Optional[Result], error: Optional[GatewayError], started: float,
                stream: bool) -> None:
    ms = int((time.monotonic() - started) * 1000)
    if result:
        logger.info("chat source=%s ok via=%s model=%s thinking=%s prompt=%d completion=%d thoughts=%d "
                    "finish=%s stream=%s ms=%d attempts=%s", source, result.connection, result.model,
                    result.thinking_level, result.prompt_tokens, result.completion_tokens, result.thoughts_tokens,
                    result.finish_reason, stream, ms, ",".join(result.attempts))
    elif error:
        logger.warning("chat source=%s failed status=%d stream=%s ms=%d attempts=%s (%s)", source, error.status,
                       stream, ms, ",".join(error.attempts), error)


def create_app(config_file: Optional[Path] = None):
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse, StreamingResponse

    app = FastAPI(title="OmniKeep LLM gateway", docs_url=None, redoc_url=None, openapi_url=None)

    def current_config() -> Dict[str, Any]:
        return load_config(config_file)

    @app.get("/health")
    async def health():
        return {"status": "healthy", "service": "OmniKeep LLM gateway"}

    @app.get("/v1/models")
    async def models(request: Request):
        if not source_for(request.headers.get("authorization", "")):
            return JSONResponse(_error_body(401, "Invalid gateway token"), status_code=401)
        return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "google-vertex"}
                                           for m in current_config()["models"]]}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):
        source = source_for(request.headers.get("authorization", ""))
        if not source:
            return JSONResponse(_error_body(401, "Invalid gateway token"), status_code=401)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse(_error_body(400, "Body is not JSON"), status_code=400)
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
            return JSONResponse(_error_body(400, "messages must be a list of objects"), status_code=400)
        fmt = body.get("response_format") or {}
        options = {"temperature": body.get("temperature"),
                   "json": isinstance(fmt, dict) and fmt.get("type") in ("json_object", "json_schema")}
        stream = bool(body.get("stream"))
        include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
        config = current_config()
        started = time.monotonic()
        completion_id = "chatcmpl-" + uuid.uuid4().hex
        created = int(time.time())

        if not stream:
            try:
                result = await complete(messages, source, options, config)
            except GatewayError as exc:
                _log_result(source, None, exc, started, False)
                return JSONResponse(_error_body(exc.status, str(exc)), status_code=exc.status,
                                    headers=_error_headers(exc))
            _log_result(source, result, None, started, False)
            return JSONResponse(
                {"id": completion_id, "object": "chat.completion", "created": created, "model": result.model,
                 "choices": [{"index": 0, "message": {"role": "assistant", "content": result.text},
                              "finish_reason": result.finish_reason}],
                 "usage": _usage(result)},
                headers={"x-omnikeep-connection": result.connection, "x-omnikeep-model": result.model,
                         "x-omnikeep-thinking": result.thinking_level})

        # A high-thinking answer can take minutes. A failure within the first seconds (every connection
        # rate limited) still gets its real status; after that the stream has begun with 200 and
        # comment lines keep the caller's idle timer alive until the answer comes.
        task = asyncio.create_task(complete(messages, source, options, config))
        await asyncio.wait({task}, timeout=KEEPALIVE_SECONDS)
        if task.done() and task.exception() is not None:
            exc = task.exception()
            if not isinstance(exc, GatewayError):
                logger.exception("Gateway failed", exc_info=exc)
                exc = GatewayError(500, "The gateway failed", [])
            _log_result(source, None, exc, started, True)
            return JSONResponse(_error_body(exc.status, str(exc)), status_code=exc.status,
                                headers=_error_headers(exc))

        async def events():
            try:
                while not task.done():
                    done, _ = await asyncio.wait({task}, timeout=KEEPALIVE_SECONDS)
                    if not done:
                        yield ": keepalive\n\n"
                try:
                    try:
                        result = task.result()
                    except GatewayError:
                        raise
                    except Exception as unexpected:
                        logger.exception("Gateway failed", exc_info=unexpected)
                        raise GatewayError(500, "The gateway failed", []) from unexpected
                except GatewayError as exc:
                    _log_result(source, None, exc, started, True)
                    yield "data: " + json.dumps(_error_body(exc.status, str(exc))) + "\n\n"
                    yield "data: [DONE]\n\n"
                    return
                _log_result(source, result, None, started, True)
                base = {"id": completion_id, "object": "chat.completion.chunk", "created": created,
                        "model": result.model}
                yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {
                    "role": "assistant", "content": result.text}, "finish_reason": None}]}, ensure_ascii=False) + "\n\n"
                yield "data: " + json.dumps({**base, "choices": [{"index": 0, "delta": {},
                                                                  "finish_reason": result.finish_reason}]}) + "\n\n"
                if include_usage:
                    yield "data: " + json.dumps({**base, "choices": [], "usage": _usage(result)}) + "\n\n"
                yield "data: [DONE]\n\n"
            finally:
                if not task.done():
                    task.cancel()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"cache-control": "no-cache", "x-omnikeep-thinking": config["thinking_level"]})

    return app
