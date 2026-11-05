"""Fallback chain over a slot's connections (docs/ai_provider_options_2026-11.md §5).

Every call starts again at the primary connection (position 0). Per member:
  429 / 5xx          the member's own backoff runs first (OpenAICompatibleProvider
                     retries 429 twice honouring Retry-After; the SDK retries 5xx);
                     when that is used up the member cools down and the next one is tried
  401 / 403 / 404    move on at once
  disabled key       (error_translate: action_required) the member is skipped until
                     the connection is edited or tested again
Members cooling down or waiting for a person are skipped while another member
can still take the call; when none can, every member is tried anyway so the
error reaches the caller. If every member failed and one of them was rate
limited, that rate-limit error is raised, so the queue worker backs off
instead of failing the item.
"""
import logging
from typing import Any, List, Optional, Tuple

from app import ai_status
from app.error_translate import classify
from app.providers.base import BaseLLMProvider

logger = logging.getLogger("omnikeep.providers.chain")

DEFAULT_COOLDOWN = 60.0
SERVER_COOLDOWN = 30.0


class Member:
    def __init__(self, provider: Any, status_key: str, label: str):
        self.provider = provider
        self.status_key = status_key
        self.label = label


class ChainProvider(BaseLLMProvider):
    def __init__(self, members: List[Member], slot: str = "analysis"):
        if not members:
            raise ValueError("A chain needs at least one connection")
        self.members = members
        self.slot = slot

    def __getattr__(self, name: str):
        # Callers that reach into the primary provider (app/parsers/reel.py uses .client,
        # .model and the Gemini key rotation) keep working.
        if name.startswith("__") or name in ("members", "slot"):
            raise AttributeError(name)
        return getattr(self.members[0].provider, name)

    def _order(self, method: str) -> List[Member]:
        able = [m for m in self.members if callable(getattr(m.provider, method, None))]
        ready = [m for m in able if not ai_status.unusable(m.status_key)]
        return ready or able

    async def _run(self, method: str, *args, **kwargs):
        order = self._order(method)
        if not order:
            raise AttributeError(f"No connection in the {self.slot} slot supports {method}")
        last: Optional[BaseException] = None
        rate_limited: Optional[BaseException] = None
        for index, member in enumerate(order):
            try:
                return await getattr(member.provider, method)(*args, **kwargs)
            except Exception as exc:
                info = classify(exc)
                last = exc
                if info["kind"] == "rate_limit":
                    rate_limited = rate_limited or exc
                    ai_status.set_cooldown(member.status_key, _retry_after(exc) or DEFAULT_COOLDOWN)
                elif info["kind"] in ("server", "connection"):
                    ai_status.set_cooldown(member.status_key, SERVER_COOLDOWN)
                if info["status"] is not None or info["kind"] in ("connection", "blocked"):
                    # The provider recorded HTTP failures itself; make sure the hint is current.
                    current = ai_status.get(member.status_key)
                    if current.get("ok", True):
                        ai_status.record_failure(member.status_key, info["status"], f"{type(exc).__name__}: {exc}",
                                                 member.label)
                if index + 1 < len(order):
                    logger.warning("[%s] %s failed (%s: %s), trying %s", self.slot, member.label or "connection",
                                   info["kind"], info["status"], order[index + 1].label or "the next connection")
        raise rate_limited or last

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return await self._run("generate_text", prompt, system_prompt)

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None):
        return await self._run("generate_json", prompt, system_prompt)

    async def analyze_youtube(self, youtube_url: str, prompt: str):
        return await self._run("analyze_youtube", youtube_url, prompt)


def _retry_after(exc: BaseException) -> Optional[float]:
    try:
        value = float(exc.response.headers.get("retry-after"))  # type: ignore[attr-defined]
    except Exception:
        return None
    return value if value > 0 else None


def describe(chain: ChainProvider) -> List[Tuple[str, str]]:
    return [(m.status_key, m.label) for m in chain.members]
