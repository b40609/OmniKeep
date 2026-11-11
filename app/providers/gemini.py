import asyncio
import itertools
import threading
import json
import re
from typing import Optional, List, Dict, Any
from app.providers.base import BaseLLMProvider, EmptyResponseError, require_text
from app.config import settings

# google-genai sets no timeout, so a stalled connection waits forever (seen 2026-11-07: five
# batch calls hung for 8 hours). A high-thinking answer can take several minutes; video longer.
TIMEOUT_MS = 900_000


def genai_client(key: str, vertexai: bool = False):
    """A google-genai client for one key, AI Studio or Vertex AI express mode, with a timeout."""
    from google import genai
    from google.genai import types as gtypes
    options = gtypes.HttpOptions(timeout=TIMEOUT_MS)
    if vertexai:
        return genai.Client(api_key=key, vertexai=True, http_options=options)
    return genai.Client(api_key=key, http_options=options)


async def _generate_content(client, status_key: str = "gemini", label: str = "", rate_limiter=None, **kwargs):
    """Run `generate_content` without blocking the event loop.

    google-genai ships a native async client (`client.aio`); use it when
    present. On SDKs without it, push the synchronous call onto a worker
    thread so a slow Gemini request (YouTube analysis can take tens of
    seconds) can no longer freeze every other request in the process.
    """
    from app import ai_status, ai_usage

    async def call():
        aio = getattr(client, "aio", None)
        if aio is not None:
            return await aio.models.generate_content(**kwargs)
        return await asyncio.to_thread(client.models.generate_content, **kwargs)

    try:
        if rate_limiter is None:
            response = await call()
        else:
            async with rate_limiter.slot():
                response = await call()
    except Exception as exc:
        code = getattr(exc, "code", None)
        if rate_limiter is not None and code == 429:
            rate_limiter.on_rate_limited(None)
        ai_status.record_failure(status_key, code if isinstance(code, int) else None,
                                 f"{type(exc).__name__}: {exc}", label)
        ai_usage.record_failure(status_key)
        raise
    if rate_limiter is not None:
        rate_limiter.on_success()
    ai_status.record_success(status_key, label)
    ai_usage.record_success(status_key, response)
    return response


class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_keys: Optional[List[str]] = None, model: Optional[str] = None,
                 rate_limiter=None, status_key: str = "gemini", label: str = "", vertexai: bool = False,
                 thinking_level: Optional[str] = None):
        self.keys = api_keys if api_keys is not None else settings.gemini_keys
        self.model = model or settings.GEMINI_MODEL
        self.limiter = rate_limiter
        self.status_key = status_key
        self.label = label
        self.vertexai = vertexai  # Vertex AI (Agent Platform) express mode instead of AI Studio
        self.thinking_level = thinking_level or None  # "low" | "medium" | "high"; None: the model's default
        self._key_cycle = itertools.cycle(self.keys) if self.keys else None
        self._lock = threading.Lock()

    def make_client(self, key: str):
        """A google-genai client for one key: AI Studio, or Vertex AI express mode."""
        return genai_client(key, self.vertexai)

    def _config(self, **kwargs):
        """GenerateContentConfig with the connection's thinking level, when one is set."""
        from google.genai import types as gtypes
        if self.thinking_level:
            kwargs["thinking_config"] = gtypes.ThinkingConfig(thinking_level=self.thinking_level)
        return gtypes.GenerateContentConfig(**kwargs)

    def _get_next_key(self) -> Optional[str]:
        if not self._key_cycle:
            return None
        with self._lock:
            return next(self._key_cycle)

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        key = self._get_next_key()
        if not key:
            raise ValueError("No GEMINI_API_KEYS configured.")

        from google import genai
        from google.genai import types as gtypes

        client = self.make_client(key)
        contents = []
        if system_prompt:
            contents.append(system_prompt + "\n\n")
        contents.append(prompt)

        response = await _generate_content(
            client, self.status_key, self.label, self.limiter,
            model=self.model,
            contents=contents,
            config=self._config(
                temperature=0.3,
            )
        )
        return response.text or ""

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        key = self._get_next_key()
        if not key:
            raise ValueError("No GEMINI_API_KEYS configured.")

        from google import genai
        from google.genai import types as gtypes

        client = self.make_client(key)
        full_prompt = (system_prompt + "\n\n" if system_prompt else "") + prompt + "\n\nReturn ONLY a valid JSON object."

        response = await _generate_content(
            client, self.status_key, self.label, self.limiter,
            model=self.model,
            contents=[full_prompt],
            config=self._config(
                temperature=0.2,
                response_mime_type="application/json"
            )
        )
        return json.loads(self._answer_text(response))

    def _answer_text(self, response) -> str:
        """The answer's text. An empty answer (a blocked prompt, or thinking that used up the
        output) is a failure: it used to become "{}", which callers took for a result."""
        from app import ai_status
        try:
            return require_text(response.text, self.label)
        except EmptyResponseError as exc:
            ai_status.record_failure(self.status_key, None, str(exc), self.label)
            raise

    async def analyze_youtube(self, youtube_url: str, prompt: str) -> Dict[str, Any]:
        """
        Natively pass YouTube URL to Gemini model without local download.
        Google's servers process video, visual, and audio directly.
        """
        key = self._get_next_key()
        if not key:
            raise ValueError("No GEMINI_API_KEYS configured for YouTube analysis.")

        from google import genai
        from google.genai import types as gtypes

        client = self.make_client(key)

        response = await _generate_content(
            client, self.status_key, self.label, self.limiter,
            model=self.model,
            contents=[
                gtypes.Part.from_uri(
                    file_uri=youtube_url,
                    mime_type="video/youtube",
                ),
                prompt + "\n\nOutput ONLY a valid JSON object matching the requested schema."
            ],
            config=self._config(
                temperature=0.3,
                response_mime_type="application/json"
            )
        )
        raw = self._answer_text(response)
        try:
            return json.loads(raw)
        except Exception:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
            if match:
                raw = match.group(1)
            return json.loads(raw.strip())
