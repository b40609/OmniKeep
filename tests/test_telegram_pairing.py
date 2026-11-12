"""Telegram owners are bound only through a one-time link from the signed-in web app."""
import re
import time
from contextlib import closing

from fastapi.testclient import TestClient
import pytest

from app import app_settings
from app.bot import telegram_bot
from app.bot.telegram_bot import TelegramBot
from app.config import settings
from app.database import get_db_connection
from app.main import app

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}
STRANGER, OWNER, FRIEND = 1111, 2222, 3333


class FakeBot(TelegramBot):
    def __init__(self):
        super().__init__(token="synthetic-token")
        self.sent = []
        self.reachable = True

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

    async def send_api(self, method, data):
        if not self.reachable:
            raise OSError("network down")
        assert method == "getMe"
        return {"ok": True, "result": {"username": "omnikeep_fixture_bot"}}


def _message(user_id, text, chat_type="private"):
    chat_id = user_id if chat_type == "private" else -100123
    return {"update_id": 1, "message": {"message_id": 7, "chat": {"id": chat_id, "type": chat_type},
                                        "from": {"id": user_id}, "text": text}}


def _saved_owners():
    """The binding as stored in the app's settings table (None when nothing was saved)."""
    with closing(get_db_connection()) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = 'TELEGRAM_ALLOWED_USER_IDS'").fetchone()
    return None if row is None else row["value"]


@pytest.fixture
def no_owners(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", "")


@pytest.fixture
def bot(monkeypatch):
    fake = FakeBot()
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "synthetic-token")
    monkeypatch.setattr(telegram_bot, "_bot_instance", fake)
    return fake


def _code():
    with TestClient(app) as client:
        res = client.post("/api/telegram/pairing", headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()["link"].split("start=", 1)[1]


async def test_messaging_first_binds_nobody(bot, no_owners):
    await bot.handle_update(_message(STRANGER, "hello"))
    await bot.handle_update(_message(STRANGER, "/start"))
    assert settings.telegram_allowed_ids == []
    assert _saved_owners() is None
    assert len(bot.sent) == 2 and all("還沒有綁定擁有者" in text for _, text in bot.sent)
    assert str(STRANGER) in bot.sent[0][1]  # their ID, so they can tell the owner


async def test_pairing_link_binds_its_first_user_once(bot, no_owners, monkeypatch, isolated_runtime):
    with TestClient(app) as client:
        pairing = client.post("/api/telegram/pairing", headers=HEADERS).json()
    assert pairing["link"].startswith("https://t.me/omnikeep_fixture_bot?start=")
    code = pairing["link"].split("start=", 1)[1]
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,64}", code)  # Telegram's start-parameter alphabet
    assert time.time() + 590 < pairing["expires_at"] <= time.time() + 600

    monkeypatch.chdir(isolated_runtime)  # the server's working directory is not the project
    await bot.handle_update(_message(OWNER, f"/start {code}"))

    assert settings.telegram_allowed_ids == [OWNER]
    assert "已綁定" in bot.sent[-1][1]
    assert _saved_owners() == str(OWNER)  # saved in the app, survives a restart
    assert not (isolated_runtime / ".env").exists()  # never written to a .env file

    await bot.handle_update(_message(STRANGER, f"/start {code}"))  # the same link, again
    assert settings.telegram_allowed_ids == [OWNER]
    assert "無效或已過期" in bot.sent[-1][1]


async def test_wrong_expired_and_replaced_codes_bind_nobody(bot, no_owners, monkeypatch):
    replaced = _code()
    current = _code()
    await bot.handle_update(_message(OWNER, "/start not-the-code"))
    await bot.handle_update(_message(OWNER, f"/start {replaced}"))
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 601)
    await bot.handle_update(_message(OWNER, f"/start {current}"))
    assert settings.telegram_allowed_ids == []
    assert all("無效或已過期" in text for _, text in bot.sent)


async def test_links_only_work_in_a_private_chat(bot, no_owners):
    code = _code()
    await bot.handle_update(_message(OWNER, f"/start@omnikeep_fixture_bot {code}", chat_type="group"))
    assert settings.telegram_allowed_ids == []
    await bot.handle_update(_message(OWNER, f"/start {code}"))  # the group attempt did not use it up
    assert settings.telegram_allowed_ids == [OWNER]


async def test_existing_owners_hear_about_a_new_binding(bot, no_owners, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", str(OWNER))
    await bot.handle_update(_message(FRIEND, f"/start {_code()}"))
    assert settings.telegram_allowed_ids == [OWNER, FRIEND]
    assert _saved_owners() == f"{OWNER},{FRIEND}"
    assert any(chat == OWNER and str(FRIEND) in text and "設定" in text for chat, text in bot.sent)


async def test_binding_that_cannot_be_saved_says_so(bot, no_owners, monkeypatch):
    def broken_save(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(app_settings, "save", broken_save)
    await bot.handle_update(_message(OWNER, f"/start {_code()}"))
    assert settings.telegram_allowed_ids == [OWNER]  # still allowed until the next restart
    assert "沒有存進資料庫" in bot.sent[-1][1]


def test_status_and_pairing_api(bot, no_owners, monkeypatch):
    with TestClient(app) as client:
        assert client.post("/api/telegram/pairing").status_code == 401
        assert client.get("/api/telegram/status", headers=HEADERS).json() == {
            "configured": True, "bound_user_ids": [], "pairing_expires_at": None}
        client.post("/api/telegram/pairing", headers=HEADERS)
        assert client.get("/api/telegram/status", headers=HEADERS).json()["pairing_expires_at"] > time.time()

        bot.reachable = False
        bot._username = None
        assert client.post("/api/telegram/pairing", headers=HEADERS).status_code == 502
        monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
        assert client.post("/api/telegram/pairing", headers=HEADERS).status_code == 503
        assert client.get("/api/telegram/status", headers=HEADERS).json()["configured"] is False
