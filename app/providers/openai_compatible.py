import json
import re
from typing import Optional, Dict, Any
from openai import AsyncOpenAI
from app.providers.base import BaseLLMProvider
from app.config import settings

class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, model: Optional[str] = None):
        self.base_url = base_url or settings.OPENAI_BASE_URL
        self.api_key = api_key or settings.OPENAI_API_KEY or "dummy-key"
        self.model = model or settings.PRIMARY_MODEL
        
        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
        )

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self.client.chat.completions.create(
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

        # First attempt: Try response_format json_object
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw = response.choices[0].message.content or "{}"
            return json.loads(raw)
        except Exception:
            # Fallback attempt without response_format flag
            response = await self.client.chat.completions.create(
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
