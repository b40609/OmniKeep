"""The free-service cards stay current without an upgrade (app/catalog_remote.py, 2026-11-23)."""
import copy
import json

import pytest

from app import catalog_remote, provider_catalog


@pytest.fixture(autouse=True)
def pristine_catalog(monkeypatch, tmp_path):
    """apply() changes the cards in place; put them back after each test."""
    saved = [copy.deepcopy(c) for c in provider_catalog.CARDS]
    by_card = dict(provider_catalog.GROUP_BY_CARD)
    recommended = copy.deepcopy(provider_catalog.RECOMMENDED)
    monkeypatch.setattr(catalog_remote, "_applied_revision", None)
    monkeypatch.setattr(catalog_remote.settings, "DATABASE_PATH", str(tmp_path / "omnikeep.db"))
    monkeypatch.setattr(catalog_remote.settings, "CATALOG_AUTO_UPDATE", True)
    yield
    for card, old in zip(provider_catalog.CARDS, saved):
        card.clear()
        card.update(old)
    provider_catalog.GROUP_BY_CARD.clear()
    provider_catalog.GROUP_BY_CARD.update(by_card)
    provider_catalog.RECOMMENDED[:] = recommended


def newer(**cards):
    data = catalog_remote.export()
    data["revision"] = provider_catalog.CATALOG_REVISION + 1
    for card_id, fields in cards.items():
        data["cards"].setdefault(card_id, {}).update(fields)
    return data


def test_the_repo_file_is_the_export_of_the_cards_in_the_code():
    """Whoever edits provider_catalog.py runs `python -m app.catalog_remote --write`; installs fetch this file."""
    on_disk = json.loads(catalog_remote.REPO_FILE.read_text(encoding="utf-8"))
    assert on_disk == catalog_remote.export(), "run: python -m app.catalog_remote --write"


def test_the_revision_moves_with_every_verified_date():
    """A card checked on a later day must come with a higher revision, or installs would skip it."""
    latest = max(c.get("verified", provider_catalog.VERIFIED) for c in provider_catalog.CARDS)
    assert provider_catalog.CATALOG_REVISION // 100 >= int(latest.replace("-", ""))


def test_a_newer_file_updates_data_fields_and_the_suggested_combo():
    data = newer(groq={"model": "openai/gpt-oss-200b", "models": ["openai/gpt-oss-200b"], "limits": "新限額"})
    data["recommended"] = [{"card": "flm", "why": "只剩這條"}]
    assert catalog_remote.apply(data)
    groq = provider_catalog.card("groq")
    assert groq["model"] == "openai/gpt-oss-200b" and groq["limits"] == "新限額"
    listed = provider_catalog.catalog()
    assert listed["revision"] == data["revision"]
    assert listed["recommended"] == [{"card": "flm", "why": "只剩這條"}]


def test_where_a_key_goes_never_comes_from_the_fetched_file():
    """Cherry Studio, OpenClaw: unsigned data must never control credential destinations."""
    before = {k: copy.deepcopy(provider_catalog.card("groq")[k]) for k in ("base_url", "kind", "key_mode", "key_url", "caps")}
    data = newer(groq={"base_url": "https://evil.example/v1", "kind": "gemini", "key_mode": "none",
                       "key_url": "https://evil.example", "caps": {"extra_body": {"x": 1}}, "limits": "ok"})
    data["cards"]["evil"] = {"label": "Free GPT", "base_url": "https://evil.example/v1", "model": "gpt"}
    assert catalog_remote.apply(data)
    groq = provider_catalog.card("groq")
    assert {k: groq[k] for k in before} == before and groq["limits"] == "ok"
    assert provider_catalog.card("evil") is None  # a new card needs an upgrade, with its address in the code


@pytest.mark.parametrize("bad", [
    {"cards": {"groq": {"models": "not-a-list"}}},
    {"cards": {"groq": {"verified": "yesterday"}}},
    {"cards": {"groq": {"quota": {"requests": -1, "period": "day"}}}},
    {"cards": {"groq": {"min_interval": 99999}}},
    {"group_by_card": {"groq": "not-a-group"}},
    {"recommended": [{"card": "not-a-card", "why": "x"}]},
    {"schema": 2},
])
def test_a_file_with_any_bad_value_is_thrown_away_whole(bad):
    data = newer(groq={"limits": "should not land"})
    for key, value in bad.items():
        if key == "cards":
            data["cards"]["groq"].update(value["groq"])
        else:
            data[key] = value
    before = copy.deepcopy(provider_catalog.card("groq"))
    assert not catalog_remote.apply(data)
    assert provider_catalog.card("groq") == before


def test_an_older_or_equal_revision_is_ignored():
    data = newer(groq={"limits": "old"})
    data["revision"] = provider_catalog.CATALOG_REVISION
    assert not catalog_remote.apply(data)
    assert provider_catalog.card("groq")["limits"] != "old"
    assert catalog_remote.apply(newer(groq={"limits": "new"}))
    again = newer(groq={"limits": "replayed"})  # the same revision a second time
    assert not catalog_remote.apply(again)


def test_the_last_fetched_file_is_used_again_after_a_restart_unless_turned_off(monkeypatch):
    data = newer(groq={"limits": "cached"})
    catalog_remote.cache_path().write_text(json.dumps({"etag": "x", "data": data}), encoding="utf-8")
    monkeypatch.setattr(catalog_remote.settings, "CATALOG_AUTO_UPDATE", False)
    assert not catalog_remote.load_cached()
    monkeypatch.setattr(catalog_remote.settings, "CATALOG_AUTO_UPDATE", True)
    assert catalog_remote.load_cached()
    assert provider_catalog.card("groq")["limits"] == "cached"


class _Resp:
    def __init__(self, status, body=b"", etag=""):
        self.status_code, self._body, self.headers = status, body, {"etag": etag}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def aiter_bytes(self):
        yield self._body


class _Client:
    def __init__(self, resp, seen):
        self.resp, self.seen = resp, seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    def stream(self, method, url, headers=None):
        self.seen.append((url, headers or {}))
        return self.resp


@pytest.mark.asyncio
async def test_fetching_uses_a_newer_file_keeps_it_and_sends_the_etag_next_time(monkeypatch):
    import httpx

    seen = []
    data = newer(groq={"limits": "fetched"})
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client(_Resp(200, json.dumps(data).encode(), '"v1"'), seen))
    assert await catalog_remote.fetch_once()
    assert provider_catalog.card("groq")["limits"] == "fetched"
    assert json.loads(catalog_remote.cache_path().read_text(encoding="utf-8"))["etag"] == '"v1"'

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _Client(_Resp(304), seen))
    assert not await catalog_remote.fetch_once()
    assert seen[-1][1] == {"If-None-Match": '"v1"'}
    assert seen[0][0].startswith("https://raw.githubusercontent.com/")


@pytest.mark.asyncio
async def test_an_oversized_or_broken_answer_changes_nothing(monkeypatch):
    import httpx

    before = copy.deepcopy(provider_catalog.card("groq"))
    for resp in (_Resp(200, b"x" * (catalog_remote.MAX_BYTES + 1)), _Resp(200, b"not json"), _Resp(500)):
        monkeypatch.setattr(httpx, "AsyncClient", lambda resp=resp, **kw: _Client(resp, []))
        assert not await catalog_remote.fetch_once()
    assert provider_catalog.card("groq") == before
    assert not catalog_remote.cache_path().exists()
