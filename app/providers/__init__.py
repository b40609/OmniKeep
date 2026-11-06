"""Which provider each task uses.

get_provider(slot) builds a fallback chain (app/providers/chain.py) from the
slot's connections (app/ai_connections.py). When a slot has no connection the
older behaviour applies: the analysis slot uses the flat settings
(PRIMARY_LLM_PROVIDER, OPENAI_*, GEMINI_*), brain and radar follow analysis,
video uses GEMINI_* when keys are set.

get_primary_provider() is the analysis slot; existing call sites and the
tests that monkeypatch it keep working.
"""
from typing import Dict, Iterable, List, Optional, Tuple

from app.config import settings
from app.providers.base import BaseLLMProvider
from app.providers.chain import ChainProvider, Member
from app.providers.gemini import GeminiProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.providers.rate_limiter import AdaptiveRateLimiter

_primary_provider: Optional[BaseLLMProvider] = None
_gemini_provider: Optional[GeminiProvider] = None
_chains: Dict[Tuple[str, str, Tuple[str, ...]], Optional[BaseLLMProvider]] = {}
_limiters: Dict[int, AdaptiveRateLimiter] = {}

# Slots that use the analysis chain once their own list is used up (or empty).
FOLLOWS_ANALYSIS = ("brain", "radar")


def limiter_for(conn) -> AdaptiveRateLimiter:
    """One limiter per connection, kept across rebuilds so its learned pacing survives an edit."""
    limiter = _limiters.get(conn.id)
    if limiter is None:
        limiter = _limiters[conn.id] = AdaptiveRateLimiter(min_interval=conn.interval(),
                                                           max_concurrency=conn.concurrency())
    elif limiter._min_interval != max(0.05, conn.interval()) or limiter._concurrency != max(1, conn.concurrency()):
        limiter.reconfigure(conn.interval(), conn.concurrency())
    return limiter


def build_provider(conn, model: Optional[str] = None) -> BaseLLMProvider:
    """A provider speaking to one connection."""
    model = model or conn.model
    common = {"rate_limiter": limiter_for(conn), "status_key": conn.status_key, "label": conn.label}
    if conn.kind == "gemini":
        keys = [k for k in conn.key.split(",") if k]
        return GeminiProvider(api_keys=keys, model=model, vertexai=bool(conn.caps.get("vertex")), **common)
    base_url = conn.base_url.rstrip("/")
    if conn.kind == "ollama":
        base_url += "/v1"  # Ollama's OpenAI-compatible endpoint
    from app.ai_connections import extra_body_for
    # Never fall back to OPENAI_API_KEY: a keyless (local) server gets a placeholder.
    return OpenAICompatibleProvider(base_url=base_url, api_key=conn.key or "dummy-key", model=model,
                                    json_mode=conn.caps.get("json_mode", True) is not False,
                                    extra_body=extra_body_for(conn, model), **common)


def _legacy(slot: str) -> Optional[BaseLLMProvider]:
    global _primary_provider
    if slot == "video":
        return get_legacy_gemini_provider() if settings.gemini_keys else None
    if _primary_provider is None:
        if settings.PRIMARY_LLM_PROVIDER == "gemini" and settings.gemini_keys:
            _primary_provider = GeminiProvider()
        else:
            _primary_provider = OpenAICompatibleProvider()
    return _primary_provider


def _entries(slot: str, skip_kinds: Iterable[str]) -> List:
    from app.ai_connections import resolve
    skip = set(skip_kinds)
    return [(conn, model) for conn, model in resolve(slot) if conn.kind not in skip]


def get_provider(slot: str = "analysis", skip_kinds: Iterable[str] = ()) -> Optional[BaseLLMProvider]:
    """The provider (a fallback chain) for a task. `skip_kinds` leaves out connections the
    caller already tried itself (app/brain.py asks Ollama directly first).
    Returns None only for "video" when nothing can analyse video."""
    cache_key = (settings.DATABASE_PATH, slot, tuple(sorted(skip_kinds)))
    if cache_key in _chains:
        return _chains[cache_key]
    entries = _entries(slot, skip_kinds)
    if slot in FOLLOWS_ANALYSIS:
        seen = {conn.id for conn, _ in entries}
        entries += [(conn, model) for conn, model in _entries("analysis", ()) if conn.id not in seen]
    if entries:
        provider: Optional[BaseLLMProvider] = ChainProvider(
            [Member(build_provider(conn, model), conn.status_key, conn.label) for conn, model in entries], slot)
    else:
        provider = _legacy("video" if slot == "video" else "analysis")
    _chains[cache_key] = provider
    return provider


def get_primary_provider() -> BaseLLMProvider:
    return get_provider("analysis")


def get_legacy_gemini_provider() -> GeminiProvider:
    global _gemini_provider
    if _gemini_provider is None:
        _gemini_provider = GeminiProvider()
    return _gemini_provider


def get_gemini_provider():
    """The video slot (YouTube analysis, reel vision and audio fallbacks)."""
    return get_provider("video") or get_legacy_gemini_provider()


def has_video_provider() -> bool:
    return get_provider("video") is not None


def reset_providers() -> None:
    """Forget cached providers so the next call uses the keys and models saved just now."""
    global _primary_provider, _gemini_provider
    _primary_provider = None
    _gemini_provider = None
    _chains.clear()
