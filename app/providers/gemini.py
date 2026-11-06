import asyncio
import itertools
import threading
import json
import re
from typing import Optional, List, Dict, Any
from app.providers.base import BaseLLMProvider
from app.config import settings


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
                 rate_limiter=None, status_key: str = "gemini", label: str = ""):
        self.keys = api_keys if api_keys is not None else settings.gemini_keys
        self.model = model or settings.GEMINI_MODEL
        self.limiter = rate_limiter
        self.status_key = status_key
        self.label = label
        self._key_cycle = itertools.cycle(self.keys) if self.keys else None
        self._lock = threading.Lock()

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

        client = genai.Client(api_key=key)
        contents = []
        if system_prompt:
            contents.append(system_prompt + "\n\n")
        contents.append(prompt)

        response = await _generate_content(
            client, self.status_key, self.label, self.limiter,
            model=self.model,
            contents=contents,
            config=gtypes.GenerateContentConfig(
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

        client = genai.Client(api_key=key)
        full_prompt = (system_prompt + "\n\n" if system_prompt else "") + prompt + "\n\nReturn ONLY a valid JSON object."

        response = await _generate_content(
            client, self.status_key, self.label, self.limiter,
            model=self.model,
            contents=[full_prompt],
            config=gtypes.GenerateContentConfig(
                temperature=0.2,
                response_mime_type="application/json"
            )
        )
        raw = response.text or "{}"
        return json.loads(raw)

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

        client = genai.Client(api_key=key)

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
            config=gtypes.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json"
            )
        )
        raw = response.text or "{}"
        try:
            return json.loads(raw)
        except Exception:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
            if match:
                raw = match.group(1)
            return json.loads(raw.strip())
