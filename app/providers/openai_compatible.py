import asyncio
import json
import logging
import re
from typing import Optional, Dict, Any
from openai import AsyncOpenAI, RateLimitError
from app.providers.base import BaseLLMProvider
from app.providers.rate_limiter import limiter
from app.config import settings

logger = logging.getLogger("omnikeep.openai_provider")


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.api_key = api_key or settings.OPENAI_API_KEY or "dummy-key"
        self.model = model or settings.PRIMARY_MODEL

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    async def _chat(self, **kwargs):
        """One paced LLM call. Short 429 blips are absorbed here with up to two
        patient retries (honoring Retry-After); sustained limits re-raise so the
        queue worker's long-cooldown logic takes over. Concurrency slots are
        never held across backoff sleeps."""
        waits = (None, 5.0, 15.0)  # first try, then two backoff presets
        last_exc: Optional[Exception] = None
        for attempt, preset_wait in enumerate(waits):
            async with limiter.slot():
                try:
                    response = await self.client.chat.completions.create(**kwargs)
                    limiter.on_success()
                    return response
                except RateLimitError as e:
                    last_exc = e
                    retry_after = None
                    try:
                        retry_after = float(e.response.headers.get("retry-after"))
                    except Exception:
                        pass
                    limiter.on_rate_limited(retry_after)
                    if attempt == len(waits) - 1:
                        break
                    wait = min(max(retry_after or preset_wait or 5.0, 2.0), 90.0)
                    logger.warning(
                        f"[Agnes] Rate limited — waiting {wait:.0f}s before retry "
                        f"{attempt + 1}/{len(waits) - 1}"
                    )
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
        return response.choices[0].message.content or ""

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
            response = await self._chat(
                model=self.model,
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw = response.choices[0].message.content or "{}"
            return json.loads(raw)
        except RateLimitError:
            raise
        except Exception:
            # Fallback attempt without response_format flag
            response = await self._chat(
                model=self.model,
                messages=messages,
                temperature=0.2,
            )
            raw = response.choices[0].message.content or "{}"
            # Extract JSON block using regex if wrapped in markdown
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw)
            if match:
                raw = match.group(1)
            return json.loads(raw.strip())
