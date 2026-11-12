from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class EmptyResponseError(RuntimeError):
    """The model answered, but with no text at all.

    Seen with reasoning models whose whole answer went into thinking. Raised instead of
    passing an empty object off as a result, so a fallback chain (app/providers/chain.py)
    moves on to its next connection and the caller never saves an analysis that is not there.
    """

    def __init__(self, label: str = ""):
        self.label = label
        who = f"「{label}」的" if label else ""
        super().__init__(f"{who}模型回了空白內容，沒有可用的文字。")


def require_text(text: Optional[str], label: str = "") -> str:
    """The model's text as it is; EmptyResponseError when there is none."""
    if not (text or "").strip():
        raise EmptyResponseError(label)
    return text


class BaseLLMProvider(ABC):
    """
    Abstract interface for LLM operations.
    Decouples OmniKeep from specific AI vendors (Agnes AI, OpenAI, Gemini, Ollama).
    """

    @abstractmethod
    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Generate raw text response."""
        pass

    @abstractmethod
    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        """Generate structured JSON response.

        Raises when there is no result (the SDK's error, EmptyResponseError, or
        json.JSONDecodeError for text that is not JSON); never returns None or a made-up {}.
        """
        pass


class NoAIConnectionError(RuntimeError):
    """Nothing is set up to answer: no AI connection, and none of the older settings.

    Raised without sending anything. The older default (api.openai.com with no key) used to be
    called anyway, which sent the page's text to a third party only to get a 401 back.
    """

    def __init__(self):
        super().__init__("還沒有接上 AI：到「設定 › AI」新增一條 AI 連線。")


class UnconfiguredProvider(BaseLLMProvider):
    """Stands in for the analysis provider while no AI is set up; every call raises
    NoAIConnectionError. The pipeline checks for it and keeps the item without an analysis."""

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        raise NoAIConnectionError()

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None) -> Dict[str, Any]:
        raise NoAIConnectionError()
