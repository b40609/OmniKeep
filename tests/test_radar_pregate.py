"""The radar pre-gate looks for muted and trained tags as whole terms in the title and the
opening of the content, never in the link."""
import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.database import get_item_by_id, tune_topic_signal
from app.radar import scheduler
from app.radar.adapters.base import RawFeedItem
from app.radar.scheduler import build_weight_index, muted_tag_hit, pregate_item, tag_in_text


def _muted(*tags):
    for tag in tags:
        tune_topic_signal(tag, "mute")
    return build_weight_index()


def _blocked(index, title, url="https://example.com/post", content=""):
    return pregate_item(title, url, content, index)[1]


def _raw(url, title, content=""):
    return RawFeedItem(url=url, title=title, content=content, source_id="s1", source_type="rss")


# ── Short Latin tags: whole terms only ───────────────────────

@pytest.mark.parametrize("title", [
    "OpenAI 發表新模型",
    "How to write a better email",
    "We maintain 300 packages",
    "Main branch protection rules",
    "Hawaii travel guide",
])
def test_a_short_muted_tag_is_not_found_inside_longer_words(title):
    assert not _blocked(_muted("AI"), title)


@pytest.mark.parametrize("title", [
    "AI 模型的新進展",
    "Building an AI agent",
    "企業導入AI的三個步驟",
    "AI-powered search",
    "The state of AI.",
])
def test_a_short_muted_tag_is_found_as_a_term_of_its_own(title):
    index = _muted("AI")
    assert _blocked(index, title)
    assert muted_tag_hit(title, "", index) == "ai"


def test_the_content_is_read_like_the_title_but_only_its_opening():
    index = _muted("AI")
    assert _blocked(index, "Weekly notes", content="This week: an AI agent that files bugs.")
    assert not _blocked(index, "Weekly notes", content="We maintain the email gateway of OpenAI.")
    assert not _blocked(index, "Weekly notes", content="x" * 600 + " an AI agent")


# ── The link is not matched ──────────────────────────────────

def test_a_google_news_link_survives_a_muted_go():
    index = _muted("Go")
    link = "https://news.google.com/rss/articles/CBMiabc123?oc=5"
    assert not _blocked(index, "國際油價連三週上漲", url=link)
    assert not _blocked(index, "Search update", url=link, content="Google ships a new ranking system.")
    assert _blocked(index, "Go 1.26 released", url=link)


def test_muted_words_in_the_link_do_not_drop_the_item():
    index = _muted("Crypto", "Casino")
    assert not _blocked(index, "Quarterly results", url="https://example.com/crypto/casino/2026-q3")
    assert muted_tag_hit("Quarterly results", "", index) is None


# ── Tags with symbols, CJK tags ──────────────────────────────

@pytest.mark.parametrize("tag, text, found", [
    ("C++", "Modern C++ in practice", True),
    ("C++", "現代C++：新標準整理", True),
    ("C++", "Plain C code review", False),          # "+" is a plus sign, not "one or more"
    ("C++", "The ABC++ toolkit", False),
    ("C#", "C# 13 的新功能", True),
    ("C#", "Music theory: Bc# chords", False),
    (".NET", "The .NET runtime", True),
    (".NET", "Ships with .NET.", True),
    (".NET", "internet providers", False),          # "." is a dot, not "any character"
    (".NET", "Hosted at example.net today", False),
    ("Node.js", "Node.js 24 發布", True),
    ("Node.js", "I love Node.js.", True),
    ("Node.js", "The nodexjs build tool", False),
    ("Node.js", "Edit the node.json file", False),
    ("機器學習", "深入淺出機器學習入門", True),
    ("機器學習", "機器人學習走路", False),
    ("加密貨幣", "比特幣與加密貨幣市場Q3回顧", True),
    ("生成式AI", "企業導入生成式AI的三個步驟", True),
    ("生成式AI", "生成式AIGC 工具", False),
    ("machine learning", "Intro to Machine\n  Learning", True),
])
def test_tags_are_compared_literally_and_cjk_tags_anywhere(tag, text, found):
    assert tag_in_text(scheduler._fold(tag), scheduler._fold(text)) is found
    assert _blocked(_muted(tag), text) is found


def test_a_one_character_muted_tag_never_blocks_before_analysis():
    index = _muted("C", "車")
    assert not _blocked(index, "Plan C for the launch")
    assert not _blocked(index, "電動車市場報告")


# ── Ranking uses the same matching ───────────────────────────

def test_ranking_weights_use_the_same_matching():
    tune_topic_signal("Go", "boost")
    index = build_weight_index()
    link = "https://news.google.com/rss/articles/CBMiabc123"
    assert pregate_item("Search update", link, "Google ships a new ranking system.", index) == (1.0, False)
    assert pregate_item("Going further with ergonomics", link, "", index) == (1.0, False)
    score, blocked = pregate_item("Go 1.26 released", link, "", index)
    assert not blocked and score > 1.0


# ── In a scan cycle ──────────────────────────────────────────

async def _cycle(raws, budget=5):
    class Adapter:
        async def fetch_latest(self, src):
            return raws

    analyzed = AsyncMock(return_value=None)
    with patch("app.radar.scheduler.get_all_radar_sources", return_value=[{"id": "s1", "source_type": "rss"}]), \
            patch("app.radar.scheduler.get_adapter", return_value=Adapter()), \
            patch("app.radar.scheduler.is_source_due", return_value=True), \
            patch("app.radar.scheduler.get_radar_settings",
                  return_value={"max_analyze_per_cycle": budget, "notification_mode": "silent"}), \
            patch("app.radar.scheduler._analyze_candidate", new=analyzed):
        await scheduler.run_radar_cycle(force=True, auto_digest=False)
    return {call.args[0] for call in analyzed.await_args_list}


async def test_cycle_drops_real_hits_only_and_logs_the_tag(caplog):
    _muted("AI", "Go")
    hit = _raw("https://example.com/ops-agent", "An AI agent for ops")
    lookalike = _raw("https://news.google.com/rss/articles/CBMilookalike", "OpenAI email outage: what we maintain")
    fresh = _raw("https://news.google.com/rss/articles/CBMifresh", "地方選舉開票結果")
    hit_stub = scheduler._save_deferred_stub(hit)
    lookalike_stub = scheduler._save_deferred_stub(lookalike)

    with caplog.at_level(logging.INFO, logger="omnikeep.radar"):
        analyzed = await _cycle([hit, lookalike, fresh])

    assert analyzed == {lookalike.url, fresh.url}
    assert get_item_by_id(hit_stub) is None  # the stub of a real hit is removed
    assert get_item_by_id(lookalike_stub)["analysis_status"] == "pending"
    dropped = [r.getMessage() for r in caplog.records if "Pre-gate dropped" in r.getMessage()]
    assert len(dropped) == 1 and "'ai'" in dropped[0] and hit.title in dropped[0]


async def test_a_stub_is_deleted_only_when_the_tag_is_really_in_the_text():
    raw = _raw("https://example.com/harmless", "Harmless headline")
    stub = scheduler._save_deferred_stub(raw)
    with patch("app.radar.scheduler.pregate_item", return_value=(-999.0, True)):
        await _cycle([raw])
    assert get_item_by_id(stub)["analysis_status"] == "pending"
