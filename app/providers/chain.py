"""Fallback chain over a slot's connections (docs/ai_provider_options_2026-11.md §5).

Every call starts again at the primary connection (position 0). Per member:
  429 / 5xx          the member's own backoff runs first (OpenAICompatibleProvider
                     retries 429 twice honouring Retry-After; the SDK retries 5xx);
                     when that is used up the member cools down and the next one is tried
  401 / 403 / 404    move on at once
  400 / 422          the member asks once more without response_format; if that fails
                     too, move on at once
  empty answer       (EmptyResponseError, or a member returning None) move on at once
  text, not JSON     (json.JSONDecodeError) move on at once
  disabled key       (error_translate: action_required) the member is skipped until
                     the connection is edited or tested again
Every Exception moves on to the next member; only cancellation goes straight up.

The order adjusts itself (2026-11-17: free routes come and go, and the owner should not have to
notice and reorder by hand). The owner's order is the preference; a member that keeps failing is
put behind the others for a while, by what went wrong (COOLDOWNS), and comes back by itself: the
first call after the pause tries it again, and one success clears its record.
  model gone (404)          6 hours    free routes get retired without notice
  needs payment (402)       6 hours
  blocked network           30 minutes
  bad answers (not JSON, empty, refused) or refused key (401/403), from the 2nd in a row:
                            10 minutes, doubling, at most 2 hours (a first one may be a fluke)
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
from app.providers.base import BaseLLMProvider, EmptyResponseError

logger = logging.getLogger("omnikeep.providers.chain")

DEFAULT_COOLDOWN = 60.0
SERVER_COOLDOWN = 30.0
# kind -> (seconds, what the settings page says)
COOLDOWNS = {
    "not_found": (6 * 3600.0, "模型目前下架或改名"),
    "quota": (6 * 3600.0, "要付款或額度用完"),
    "blocked": (1800.0, "網路被攔截"),
}
BAD_ANSWER_KINDS = {"other": "回應格式不對", "empty": "回應是空白", "invalid_output": "回應格式不對",
                    "bad_request": "請求被拒", "auth": "被拒絕（金鑰或權限）"}
BAD_ANSWER_FIRST, BAD_ANSWER_MAX = 600.0, 7200.0


def _pause_for(member: "Member", info: dict) -> None:
    kind = info.get("kind")
    if info.get("action_required"):
        return  # skipped until the owner edits or tests it (ai_status.unusable)
    if kind in COOLDOWNS:
        seconds, reason = COOLDOWNS[kind]
        ai_status.set_cooldown(member.status_key, seconds, reason)
    elif kind in BAD_ANSWER_KINDS:
        streak = ai_status.streak(member.status_key)
        if streak >= 2:
            seconds = min(BAD_ANSWER_MAX, BAD_ANSWER_FIRST * 2 ** (streak - 2))
            ai_status.set_cooldown(member.status_key, seconds, f"連續 {streak} 次{BAD_ANSWER_KINDS[kind]}")


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
        if method == "describe_image":
            able = [m for m in able if getattr(m.provider, "vision", True) is not False]
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
                result = await getattr(member.provider, method)(*args, **kwargs)
                if result is None:
                    # No method has None as an answer; taken for one, the chain stopped here.
                    raise EmptyResponseError(member.label)
                ai_status.clear_streak(member.status_key)
                return result
            except Exception as exc:
                info = classify(exc)
                last = exc
                if method == "describe_image" and info["kind"] not in ("rate_limit", "server", "connection", "blocked"):
                    # a model that cannot read this image may still analyse text well: no pause
                    if index + 1 < len(order):
                        logger.warning("[%s] %s could not read the image (%s: %s), trying %s", self.slot,
                                       member.label or "connection", info["kind"], info["status"],
                                       order[index + 1].label or "the next connection")
                    continue
                ai_status.bump_streak(member.status_key)
                if info["kind"] == "rate_limit":
                    rate_limited = rate_limited or exc
                    ai_status.set_cooldown(member.status_key, _retry_after(exc) or DEFAULT_COOLDOWN, "限流")
                elif info["kind"] in ("server", "connection"):
                    ai_status.set_cooldown(member.status_key, SERVER_COOLDOWN, "暫時連不上")
                else:
                    _pause_for(member, info)
                if info["status"] is not None or info["kind"] in ("connection", "blocked"):
                    # The provider recorded HTTP failures itself; make sure the hint is current.
                    current = ai_status.get(member.status_key)
                    if current.get("ok", True):
                        ai_status.record_failure(member.status_key, info["status"], f"{type(exc).__name__}: {exc}",
                                                 member.label)
                if index + 1 < len(order):
                    logger.warning("[%s] %s failed (%s: %s; %s: %.160s), trying %s", self.slot, member.label or "connection",
                                   info["kind"], info["status"], type(exc).__name__, " ".join(str(exc).split()),
                                   order[index + 1].label or "the next connection")
        raise rate_limited or last

    async def generate_text(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        return await self._run("generate_text", prompt, system_prompt)

    async def generate_json(self, prompt: str, system_prompt: Optional[str] = None):
        return await self._run("generate_json", prompt, system_prompt)

    async def analyze_youtube(self, youtube_url: str, prompt: str):
        return await self._run("analyze_youtube", youtube_url, prompt)

    async def describe_image(self, image: bytes, prompt: str, mime_type: str = "image/jpeg") -> str:
        return await self._run("describe_image", image, prompt, mime_type)


def _retry_after(exc: BaseException) -> Optional[float]:
    try:
        value = float(exc.response.headers.get("retry-after"))  # type: ignore[attr-defined]
    except Exception:
        return None
    return value if value > 0 else None


def describe(chain: ChainProvider) -> List[Tuple[str, str]]:
    return [(m.status_key, m.label) for m in chain.members]
