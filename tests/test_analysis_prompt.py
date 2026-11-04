"""The analysis prompt is personalised only from what the owner enters in the app."""
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app import pipeline
from app.main import app

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}


def test_profile_saved_in_the_app_reaches_the_next_prompt(monkeypatch):
    # /api/brain/status asks Ollama for its models; answer locally instead of the network.
    import httpx
    from app import brain
    real_client = httpx.Client
    ollama = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": []}))
    monkeypatch.setattr(brain.httpx, "Client", lambda **kw: real_client(transport=ollama, **kw))

    with TestClient(app) as client:
        res = client.put("/api/settings", headers=HEADERS, json={"values": {
            "USER_BACKGROUND": "嵌入式工程師", "LOCAL_HARDWARE": "Jetson Orin 8GB"}})
        assert res.status_code == 200, res.text
        groups = {g["id"]: [f["key"] for f in g["fields"]] for g in res.json()["groups"]}
        assert groups["profile"] == ["USER_BACKGROUND", "LOCAL_HARDWARE", "ANALYSIS_DEPTH"]

        prompt = pipeline.analysis_system_prompt()
        assert "使用者背景錨點：嵌入式工程師。" in prompt
        assert "（Jetson Orin 8GB）" in prompt

        status = client.get("/api/brain/status", headers=HEADERS).json()
        assert status["device_acceleration"] == "Jetson Orin 8GB"


def test_prompt_is_neutral_without_profile_settings(monkeypatch):
    monkeypatch.setattr(settings, "USER_BACKGROUND", "")
    monkeypatch.setattr(settings, "LOCAL_HARDWARE", "")

    prompt = pipeline.analysis_system_prompt()

    assert "<<" not in prompt
    assert "使用者背景錨點" not in prompt
    assert "### 🖥️ 硬體需求與快速上手評估" in prompt
    assert "8 GB、16 GB、24 GB" in prompt
    assert "若附有使用者興趣設定檔" in prompt


def test_prompt_uses_background_and_hardware_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "USER_BACKGROUND", "資料工程師，在做記帳 App。")
    monkeypatch.setattr(settings, "LOCAL_HARDWARE", "RTX 4070 12GB")

    prompt = pipeline.analysis_system_prompt()

    assert "使用者背景錨點：資料工程師，在做記帳 App。\n" in prompt
    assert "結合上述使用者背景" in prompt
    assert "### 🖥️ 本機硬體適配與快速上手評估（RTX 4070 12GB）" in prompt
    assert "在本機（RTX 4070 12GB）上的運行結論" in prompt
    assert pipeline.hardware_heading() == "### 🖥️ 本機硬體適配與快速上手評估（RTX 4070 12GB）"


def test_owner_text_is_not_expanded_as_placeholder(monkeypatch):
    monkeypatch.setattr(settings, "USER_BACKGROUND", "寫了 <<HARDWARE_HEADING>> 的人")
    monkeypatch.setattr(settings, "LOCAL_HARDWARE", "")

    prompt = pipeline.analysis_system_prompt()

    assert "使用者背景錨點：寫了 <<HARDWARE_HEADING>> 的人。" in prompt


# ── Analysis depth (設定 › 個人化 › 分析深度) ──────────────────

def test_standard_depth_keeps_the_prompt_as_it_was(monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_DEPTH", "standard")
    standard = pipeline.analysis_system_prompt()
    assert "分析深度" not in standard
    for value in ("", "verbose"):  # empty or unknown values fall back to the standard prompt
        monkeypatch.setattr(settings, "ANALYSIS_DEPTH", value)
        assert pipeline.analysis_system_prompt() == standard


@pytest.mark.parametrize("depth, label", [
    ("concise", "重點摘要"), ("technical", "技術細節"), ("actionable", "含落地建議")])
def test_depth_appends_one_rule_after_the_standard_prompt(monkeypatch, depth, label):
    monkeypatch.setattr(settings, "ANALYSIS_DEPTH", "standard")
    standard = pipeline.analysis_system_prompt()
    monkeypatch.setattr(settings, "ANALYSIS_DEPTH", depth)

    prompt = pipeline.analysis_system_prompt()

    assert prompt.startswith(standard)
    assert prompt.endswith(pipeline.ANALYSIS_DEPTH_RULES[depth])
    assert f"使用者設定：{label}" in prompt
    assert "<<" not in prompt


def test_depth_saved_in_the_app_reaches_the_next_prompt():
    with TestClient(app) as client:
        res = client.put("/api/settings", headers=HEADERS, json={"values": {"ANALYSIS_DEPTH": "concise"}})
        assert res.status_code == 200, res.text
        assert "使用者設定：重點摘要" in pipeline.analysis_system_prompt()

        bad = client.put("/api/settings", headers=HEADERS, json={"values": {"ANALYSIS_DEPTH": "verbose"}})
        assert bad.status_code == 400
        assert "使用者設定：重點摘要" in pipeline.analysis_system_prompt()
