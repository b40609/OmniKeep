"""Telegram owners are bound only through a one-time link from the signed-in web app."""
import re
import time

from dotenv import dotenv_values
from fastapi.testclient import TestClient
import pytest

from app.bot import telegram_bot, telegram_pairing
from app.bot.telegram_bot import TelegramBot
from app.config import BASE_DIR, settings
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


@pytest.fixture
def env_file(monkeypatch, isolated_runtime):
    path = isolated_runtime / "deploy" / ".env"
    path.parent.mkdir()
    path.write_text("API_KEY=keep-me\nTELEGRAM_ALLOWED_USER_IDS=\n", encoding="utf-8")
    monkeypatch.setattr(telegram_pairing, "_env_file", lambda: path)
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", "")
    return path


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


async def test_messaging_first_binds_nobody(bot, env_file):
    await bot.handle_update(_message(STRANGER, "hello"))
    await bot.handle_update(_message(STRANGER, "/start"))
    assert settings.telegram_allowed_ids == []
    assert dotenv_values(env_file)["TELEGRAM_ALLOWED_USER_IDS"] == ""
    assert len(bot.sent) == 2 and all("尚未綁定" in text for _, text in bot.sent)
    assert str(STRANGER) in bot.sent[0][1]  # their ID, for setting it by hand


async def test_pairing_link_binds_its_first_user_once(bot, env_file, monkeypatch, isolated_runtime):
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
    values = dotenv_values(env_file)
    assert values["TELEGRAM_ALLOWED_USER_IDS"] == str(OWNER) and values["API_KEY"] == "keep-me"
    assert not (isolated_runtime / ".env").exists()  # no stray relative .env

    await bot.handle_update(_message(STRANGER, f"/start {code}"))  # the same link, again
    assert settings.telegram_allowed_ids == [OWNER]
    assert "無效或已過期" in bot.sent[-1][1]


async def test_wrong_expired_and_replaced_codes_bind_nobody(bot, env_file, monkeypatch):
    replaced = _code()
    current = _code()
    await bot.handle_update(_message(OWNER, "/start not-the-code"))
    await bot.handle_update(_message(OWNER, f"/start {replaced}"))
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 601)
    await bot.handle_update(_message(OWNER, f"/start {current}"))
    assert settings.telegram_allowed_ids == []
    assert all("無效或已過期" in text for _, text in bot.sent)


async def test_links_only_work_in_a_private_chat(bot, env_file):
    code = _code()
    await bot.handle_update(_message(OWNER, f"/start@omnikeep_fixture_bot {code}", chat_type="group"))
    assert settings.telegram_allowed_ids == []
    await bot.handle_update(_message(OWNER, f"/start {code}"))  # the group attempt did not use it up
    assert settings.telegram_allowed_ids == [OWNER]


async def test_existing_owners_hear_about_a_new_binding(bot, env_file, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", str(OWNER))
    await bot.handle_update(_message(FRIEND, f"/start {_code()}"))
    assert settings.telegram_allowed_ids == [OWNER, FRIEND]
    assert dotenv_values(env_file)["TELEGRAM_ALLOWED_USER_IDS"] == f"{OWNER},{FRIEND}"
    assert any(chat == OWNER and str(FRIEND) in text for chat, text in bot.sent)


async def test_binding_that_cannot_reach_env_says_so(bot, env_file, monkeypatch):
    monkeypatch.setattr(telegram_pairing, "_env_file", lambda: None)
    await bot.handle_update(_message(OWNER, f"/start {_code()}"))
    assert settings.telegram_allowed_ids == [OWNER]
    assert "無法寫入 .env" in bot.sent[-1][1]


def test_env_file_is_the_absolute_one_the_settings_read(monkeypatch):
    assert telegram_pairing._env_file() is None  # tests never touch a real .env
    monkeypatch.setitem(settings.model_config, "env_file", str(BASE_DIR / ".env"))
    assert telegram_pairing._env_file() == (BASE_DIR / ".env").resolve()
    assert telegram_pairing._env_file().is_absolute()


def test_status_and_pairing_api(bot, env_file, monkeypatch):
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
