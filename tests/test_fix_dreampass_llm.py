"""Dream Pass asks the radar slot's provider chain (設定 › AI 服務商) and falls back to the
tag-count write-up when that fails.

History: it first read a non-existent ``settings.OPENAI_MODEL`` and always fell back silently
(review-20261102 bug 1). It then posted to the flat OPENAI_* settings on its own, which an
install that only has connections does not have, so it still never reached a model there.
"""
import logging

import pytest

from app import ai_connections, ai_status, providers
from app.config import settings
from app.database import log_behavior_event, save_item, set_interest_profile
from app.radar import dreampass
from app.radar.dreampass import run_dreampass_reflection

LLM_REPLY = {
    "observations": ["最近偏好向量資料庫", "對前端框架興趣下降"],
    "suggested_profile": "LLM 產出的新畫像：關注分散式系統與向量資料庫。",
    "diff_summary": "＋ 向量資料庫\n－ 前端框架",
}
# Fields of interest the fallback used to assume for an owner who never wrote a profile.
ASSUMED_FIELDS = ("系統架構", "效能優化", "AI", "技術", "工程")


class FakeProvider:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, []

    async def generate_json(self, prompt, system_prompt=None):
        self.calls.append((prompt, system_prompt))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture(autouse=True)
def clean_providers():
    ai_status.forget()
    providers.reset_providers()
    yield
    ai_status.forget()
    providers.reset_providers()


@pytest.fixture
def chain(monkeypatch):
    """An install set up in the app only: one local connection, none of the flat settings."""
    assert settings.OPENAI_API_KEY == "" and ai_connections.needs_setup()
    box = {"provider": FakeProvider(LLM_REPLY), "built": []}

    def build(conn, model=None):
        box["built"].append(conn.base_url)
        return box["provider"]

    monkeypatch.setattr(providers, "build_provider", build)
    ai_connections.create({"card": "ollama"}, slot="analysis")  # the radar slot follows analysis
    return box


def _signals():
    liked = save_item({"url": "https://example.com/sourdough", "title_l1": "酸種麵包入門", "summary_l1": "養酵母",
                       "category_name": "Inbox", "tech_tags": ["烘焙", "酸種"]})
    disliked = save_item({"url": "https://example.com/gossip", "title_l1": "名人八卦", "summary_l1": "八卦",
                          "category_name": "Inbox", "tech_tags": ["八卦"]})
    log_behavior_event("swipe_star", item_id=str(liked))
    log_behavior_event("dampen", item_id=str(disliked))


# ── With a connection: through the radar slot ────────────────

async def test_a_connection_only_install_asks_the_radar_chain(chain):
    set_interest_profile("關注分散式系統。")

    prop = await run_dreampass_reflection(days=7)

    # The LLM result, not the heuristic, must be what gets recorded.
    assert prop["suggested_profile"] == LLM_REPLY["suggested_profile"]
    assert prop["diff_summary"] == LLM_REPLY["diff_summary"]
    assert prop["observations"] == "• 最近偏好向量資料庫\n• 對前端框架興趣下降"
    assert set(chain["built"]) == {"http://127.0.0.1:11434"}  # a loopback address is fine here
    assert len(chain["provider"].calls) == 1
    prompt, system_prompt = chain["provider"].calls[0]
    assert "關注分散式系統。" in prompt
    assert system_prompt == dreampass._DREAMPASS_SYSTEM_PROMPT


async def test_dreampass_uses_the_radar_slot(monkeypatch):
    asked = []
    fake = FakeProvider(LLM_REPLY)
    monkeypatch.setattr(dreampass, "_ai_is_set_up", lambda: True)
    monkeypatch.setattr(dreampass, "get_provider", lambda slot: asked.append(slot) or fake)

    prop = await run_dreampass_reflection(days=7)

    assert asked == ["radar"] and len(fake.calls) == 1
    assert prop["suggested_profile"] == LLM_REPLY["suggested_profile"]


# ── Provider failures: logged, then the tag-count write-up ───

async def test_a_failing_provider_is_logged_and_the_heuristic_takes_over(chain, caplog):
    chain["provider"] = FakeProvider(RuntimeError("boom-from-llm"))
    set_interest_profile("關注園藝。")
    _signals()

    with caplog.at_level(logging.WARNING, logger="omnikeep.dreampass"):
        prop = await run_dreampass_reflection(days=7)

    assert len(chain["provider"].calls) == 1
    # Falls back to heuristic ...
    assert prop["id"]
    assert prop["suggested_profile"].startswith("關注園藝。") and "烘焙" in prop["suggested_profile"]
    assert "八卦" in prop["diff_summary"]
    # ... but the failure is visible in the logs with the exception type.
    msgs = [r.getMessage() for r in caplog.records if r.name == "omnikeep.dreampass"]
    assert any("RuntimeError" in m and "boom-from-llm" in m for m in msgs), msgs


@pytest.mark.parametrize("reply", [
    {"observations": ["沒有給建議"]},
    {"suggested_profile": None, "diff_summary": "x"},
    {"suggested_profile": "   "},
    ["not", "an", "object"],
])
async def test_a_reply_without_a_profile_is_logged_and_not_recorded(chain, caplog, reply):
    chain["provider"] = FakeProvider(reply)
    set_interest_profile("關注園藝。")

    with caplog.at_level(logging.WARNING, logger="omnikeep.dreampass"):
        prop = await run_dreampass_reflection(days=7)

    assert prop["suggested_profile"] == "關注園藝。"  # the heuristic keeps the owner's own text
    msgs = [r.getMessage() for r in caplog.records if r.name == "omnikeep.dreampass"]
    assert any("suggested_profile" in m for m in msgs), msgs


async def test_reply_fields_given_as_lists_are_stored_as_lines(chain):
    chain["provider"] = FakeProvider({"observations": None, "suggested_profile": "關注烘焙。",
                                      "diff_summary": ["＋ 烘焙", "－ 八卦"]})

    prop = await run_dreampass_reflection(days=7)

    assert prop["suggested_profile"] == "關注烘焙。" and prop["diff_summary"] == "＋ 烘焙\n－ 八卦"
    assert prop["observations"]


# ── Nothing set up: no call at all ───────────────────────────

async def test_without_any_ai_set_up_no_provider_is_asked(monkeypatch):
    def unexpected(slot):
        raise AssertionError("no provider should be asked")

    monkeypatch.setattr(dreampass, "get_provider", unexpected)
    set_interest_profile("關注園藝。")

    prop = await run_dreampass_reflection(days=7)

    assert prop["id"] and prop["suggested_profile"] == "關注園藝。"


# ── The fallback assumes no field of interest ────────────────

async def test_without_profile_or_signals_the_fallback_assumes_no_field():
    prop = await run_dreampass_reflection(days=7)

    assert prop["id"] and prop["suggested_profile"] == ""
    text = prop["suggested_profile"] + prop["observations"] + prop["diff_summary"]
    assert not any(word in text for word in ASSUMED_FIELDS), text


async def test_without_a_profile_the_fallback_is_built_from_the_observed_tags_only():
    _signals()

    prop = await run_dreampass_reflection(days=7)

    assert prop["suggested_profile"] == "近期重點關注：烘焙, 酸種。 排除噪音：八卦。"
    assert not any(word in prop["suggested_profile"] for word in ASSUMED_FIELDS)
