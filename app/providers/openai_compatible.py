import asyncio
import json
import logging
import re
from typing import Optional, Dict, Any
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, DefaultAsyncHttpxClient, RateLimitError
from app import ai_status, ai_usage
from app.providers.base import BaseLLMProvider
from app.providers.rate_limiter import limiter
from app.config import settings

logger = logging.getLogger("omnikeep.openai_provider")

# What a keyless connection (a local server, or a public gateway such as Kilo) gets as its key.
PLACEHOLDER_KEY = "dummy-key"


async def _drop_placeholder_auth(request: Any) -> None:
    """Request hook of the SDK's HTTP client (its own httpx build, so the type is not httpx.Request)."""
    if request.headers.get("Authorization") == f"Bearer {PLACEHOLDER_KEY}":
        del request.headers["Authorization"]


def client_auth(api_key: str, **http_kwargs: Any) -> Dict[str, Any]:
    """AsyncOpenAI auth arguments. With the placeholder no Authorization header is sent:
    local servers ignore the header either way, while keyless public gateways (Kilo)
    answer 401 to a bearer token they do not know. The SDK insists on an auth header
    when it builds a request, so the header is dropped just before sending."""
    if not api_key or api_key == PLACEHOLDER_KEY:
        hooks = {"request": [_drop_placeholder_auth]}
        return {"api_key": PLACEHOLDER_KEY, "http_client": DefaultAsyncHttpxClient(event_hooks=hooks, **http_kwargs)}
    return {"api_key": api_key}


class ProviderUnavailableError(RuntimeError):
    """The endpoint returned an HTML access/interception page, not model output."""


def extract_completion_content(response: Any) -> str:
    """Read text from SDK completions and OpenAI-compatible raw responses."""
    if isinstance(response, str):
        response = response.lstrip("\ufeff \t\r\n")
        preview = response[:2048].lower()
        if preview.startswith(("<!doctype html", "<html", "<head", "<body")) or "blockpage.cgi" in preview:
            raise ProviderUnavailableError(
                "AI 服務回傳網路封鎖／轉址頁面，無法取得模型結果。"
                "請確認服務端點的網路存取權限，或設定其他可用的 AI 供應商。"
            )
        try:
            decoded = json.loads(response)
        except json.JSONDecodeError:
            return response
        if isinstance(decoded, str):
            return decoded
        if not isinstance(decoded, dict) or "choices" not in decoded:
            return response  # The endpoint returned model text (possibly JSON).
        response = decoded

    choices = response.get("choices") if isinstance(response, dict) else getattr(response, "choices", None)
    if not isinstance(choices, (list, tuple)) or not choices:
        raise ValueError(f"Invalid chat completion response ({type(response).__name__}): missing choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if content is None:
        return ""
    if not isinstance(content, str):
        raise ValueError(f"Invalid chat completion content type: {type(content).__name__}")
    return content


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None,
                 rate_limiter=None, status_key: str = "llm", label: str = "", json_mode: bool = True,
                 extra_body: Optional[Dict[str, Any]] = None):
        """With no arguments: the settings that predate connections (OPENAI_*), paced by the
        shared limiter. A connection (app/ai_connections.py) passes its own address, key
        (never empty: a keyless local server gets a placeholder), limiter and status key.
        `extra_body` (a connection's caps["extra_body"]) is merged into every chat request,
        e.g. {"thinking": {"type": "disabled"}} to switch a reasoning model's thinking off."""
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.api_key = api_key or settings.OPENAI_API_KEY or PLACEHOLDER_KEY
        self.model = model or settings.PRIMARY_MODEL
        self.limiter = rate_limiter or limiter
        self.status_key = status_key
        self.label = label
        self.json_mode = json_mode
        self.extra_body = dict(extra_body) if extra_body else None

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            **client_auth(self.api_key),
        )

    async def _chat(self, **kwargs):
        """One paced LLM call. Short 429 blips are absorbed here with up to two
        patient retries (honoring Retry-After); sustained limits re-raise so the
        queue worker's long-cooldown logic takes over. Concurrency slots are
        never held across backoff sleeps."""
        waits = (None, 5.0, 15.0)  # first try, then two backoff presets
        last_exc: Optional[Exception] = None
        if self.extra_body:
            kwargs["extra_body"] = {**self.extra_body, **(kwargs.get("extra_body") or {})}
        for attempt, preset_wait in enumerate(waits):
            async with self.limiter.slot():
                try:
                    response = await self.client.chat.completions.create(**kwargs)
                    self.limiter.on_success()
                    ai_status.record_success(self.status_key, self.label)
                    ai_usage.record_success(self.status_key, response)
                    return response
                except RateLimitError as e:
                    last_exc = e
                    retry_after = None
                    try:
                        retry_after = float(e.response.headers.get("retry-after"))
                    except Exception:
                        pass
                    self.limiter.on_rate_limited(retry_after)
                    if attempt == len(waits) - 1:
                        ai_status.record_failure(self.status_key, 429, str(e), self.label)
                        ai_usage.record_failure(self.status_key)
                        break
                    wait = min(max(retry_after or preset_wait or 5.0, 2.0), 90.0)
                    logger.warning(
                        f"[{self.label or 'LLM'}] Rate limited — waiting {wait:.0f}s before retry "
                        f"{attempt + 1}/{len(waits) - 1}"
                    )
                except APIStatusError as e:
                    ai_status.record_failure(self.status_key, e.status_code, str(e), self.label)
                    ai_usage.record_failure(self.status_key)
                    raise
                except APIConnectionError as e:
                    ai_status.record_failure(self.status_key, None, f"連不上 {self.base_url}（{type(e).__name__}）",
                                             self.label)
                    ai_usage.record_failure(self.status_key)
                    raise
            # Backoff outside the slot so the other lane keeps working
            await asyncio.sleep(wait)
        raise last_exc

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self._chat(
            model=self.model,
            messages=messages,
            temperature=0.3,
        )
        return extract_completion_content(response)

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        sys = system_prompt or "You are an expert technical intelligence analyst. You must output valid JSON only."
        if "JSON" not in sys:
            sys += " Always output strictly valid JSON."

        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": prompt}
        ]

        # First attempt: Try response_format json_object. Rate limits must
        # propagate (never burn a second paced request while throttled).
        try:
            if not self.json_mode:
                raise ValueError("json_object is off for this connection")
            response = await self._chat(
                model=self.model,
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw = extract_completion_content(response) or "{}"
            return json.loads(raw)
        except RateLimitError:
            raise
        except ProviderUnavailableError:
            raise  # A block page cannot be fixed by changing response_format.
        except APIConnectionError:
            raise  # a down server: the fallback chain moves on
        except APIStatusError as e:
            if e.status_code in (401, 402, 403, 404) or e.status_code >= 500:
                raise  # a dead key or a broken server: retrying without response_format cannot help
        except Exception:
            # Fallback attempt without response_format flag
            response = await self._chat(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
            raw = extract_completion_content(response) or "{}"
            # Extract JSON block using regex if wrapped in markdown
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
            if match:
                raw = match.group(1)
            return json.loads(raw.strip())
