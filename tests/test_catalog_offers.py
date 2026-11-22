"""Limited-time free offers on provider cards (Itera's ends 2026-11-24)."""
import importlib.util
from pathlib import Path

from app import provider_catalog

ROOT = Path(__file__).resolve().parents[1]


def test_a_limited_offer_says_when_it_has_ended():
    itera = provider_catalog.card("itera")
    assert itera["ends"] == "2026-11-24"
    assert not provider_catalog.ended(itera, "2026-11-24")
    assert provider_catalog.ended(itera, "2026-11-25")
    assert not provider_catalog.ended(provider_catalog.card("kilo"), "2099-01-01")
    listed = {c["id"]: c for c in provider_catalog.catalog()["cards"]}
    assert listed["kilo"]["ends"] == "" and listed["kilo"]["ended"] is False
    assert isinstance(listed["itera"]["ended"], bool)


def test_weekly_watch_flags_offers_ending_soon_or_over():
    spec = importlib.util.spec_from_file_location("free_channel_watch", ROOT / "scripts" / "free_channel_watch.py")
    watch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watch)
    assert not any("Itera" in line for line in watch.offer_lines("2026-11-01"))
    assert any("Itera" in line and "還有 4 天" in line for line in watch.offer_lines("2026-11-20"))
    assert any("Itera" in line and "已在 2026-11-24 結束" in line for line in watch.offer_lines("2026-11-25"))


def test_every_card_sits_in_a_group_that_says_how_to_use_it():
    """The service picker sorts cards by kind of free (2026-11-22); a card added without a group
    would fall into 付費或自訂 and look paid."""
    data = provider_catalog.catalog()
    groups = {g["id"]: g for g in data["groups"]}
    assert all(g["title"] and g["how"] for g in groups.values())
    assert set(provider_catalog.GROUP_BY_CARD) == {c["id"] for c in provider_catalog.CARDS}
    assert set(provider_catalog.GROUP_BY_CARD.values()) <= set(groups)
    listed = {c["id"]: c["group"] for c in data["cards"]}
    no_signup = {c["id"] for c in provider_catalog.CARDS if c.get("no_signup")}
    assert no_signup and all(listed[i] == "keyless" for i in no_signup)
    assert listed["ollama"] == "local" and listed["vertex"] == "subscription" and listed["itera"] == "grant"
