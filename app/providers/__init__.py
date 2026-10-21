from typing import Optional
from app.providers.base import BaseLLMProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.gemini import GeminiProvider
from app.config import settings

_primary_provider: Optional[BaseLLMProvider] = None
_gemini_provider: Optional[GeminiProvider] = None

def get_primary_provider() -> BaseLLMProvider:
    global _primary_provider
    if _primary_provider is None:
        if settings.PRIMARY_LLM_PROVIDER == "gemini" and settings.gemini_keys:
            _primary_provider = GeminiProvider()
        else:
            _primary_provider = OpenAICompatibleProvider()
    return _primary_provider

def get_gemini_provider() -> GeminiProvider:
    global _gemini_provider
    if _gemini_provider is None:
        _gemini_provider = GeminiProvider()
    return _gemini_provider
