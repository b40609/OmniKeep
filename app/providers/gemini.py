import itertools
import threading
import json
import re
from typing import Optional, List, Dict, Any
from app.providers.base import BaseLLMProvider
from app.config import settings

class GeminiProvider(BaseLLMProvider):
    def __init__(self, api_keys: Optional[List[str]] = None, model: Optional[str] = None):
        self.keys = api_keys if api_keys is not None else settings.gemini_keys
        self.model = model or settings.GEMINI_MODEL
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

        response = client.models.generate_content(
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

        response = client.models.generate_content(
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
        
        response = client.models.generate_content(
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
