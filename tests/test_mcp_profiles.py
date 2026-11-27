"""Tiered MCP tool profiles (lean 7-tool core default), FreeLLMAPI card & setup_cli."""
import asyncio
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import ai_connections, database, mcp_server, provider_catalog, setup_flow

ROOT = Path(__file__).resolve().parents[1]


def _load_setup_cli():
    spec = importlib.util.spec_from_file_location("setup_cli", ROOT / "scripts" / "setup_cli.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


@pytest.fixture(autouse=True)
def restore_core_profile():
    mcp_server.configure_mcp_profile("core")
    yield
    mcp_server.configure_mcp_profile("core")


def _registered_tool_names() -> set[str]:
    return {t.name for t in mcp_server.mcp._tool_manager.list_tools()}


def test_default_core_profile_exposes_only_seven_lean_tools():
    names = _registered_tool_names()
    assert len(names) == 7
    assert names == set(mcp_server.CORE_TOOL_NAMES)
    assert "omnikeep_scan" not in names
    assert "list_proposals" not in names


def test_profiles_expand_cleanly_and_reject_unknown_names():
    mcp_server.configure_mcp_profile(" , ")
    assert mcp_server.active_mcp_profile() == "core"

    mcp_server.configure_mcp_profile("review")
    assert _registered_tool_names() == set(mcp_server.CORE_TOOL_NAMES) | set(mcp_server.REVIEW_TOOL_NAMES)
    assert len(_registered_tool_names()) == 10

    mcp_server.configure_mcp_profile("setup")
    assert len(_registered_tool_names()) == 18
    assert set(mcp_server.SETUP_TOOL_NAMES) <= _registered_tool_names()

    mcp_server.configure_mcp_profile("core,review,labs")
    assert len(_registered_tool_names()) == 13
    assert mcp_server.active_mcp_profile() == "core,review,labs"

    mcp_server.configure_mcp_profile("full")
    assert len(_registered_tool_names()) == 29
    assert _registered_tool_names() == set(mcp_server.ALL_TOOL_FUNCTIONS)

    with pytest.raises(ValueError, match="不認得的 MCP profile"):
        mcp_server.configure_mcp_profile("nonexistent")


def test_invalid_env_profile_falls_back_to_core_on_import_without_crashing():
    env = {**os.environ, "OMNIKEEP_TESTING": "1", "OMNIKEEP_MCP_PROFILE": "bogus_profile_xyz"}
    code = (
        "from app import mcp_server; "
        "print(mcp_server.active_mcp_profile(), len(mcp_server.mcp._tool_manager.list_tools()))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        stdin=subprocess.DEVNULL,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "core 7"


@pytest.mark.asyncio
async def test_get_item_detail_includes_raw_even_when_analysis_mentions_error_word():
    item_id = database.save_item({
        "url": "https://example.test/detail-error-text",
        "title_l1": "錯誤處理指南",
        "summary_l1": "說明常見錯誤：如何正確重試",
        "deep_analysis": "## 常見錯誤：逾時與限流處理",
        "content_raw": "RAW_BODY_SENTINEL_12345",
    })
    out = await mcp_server.get_item_detail(item_id, include_raw=True)
    assert "RAW_BODY_SENTINEL_12345" in out


@pytest.mark.asyncio
async def test_stdio_default_profile_exposes_seven_core_tools():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {k: v for k, v in os.environ.items() if k not in ("OMNIKEEP_MCP_PROFILE", "MCP_PROFILE")}
    env["OMNIKEEP_TESTING"] = "1"
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "mcp_server.py")],
        env=env,
        cwd=str(ROOT),
    )

    async def run():
        with open(os.devnull, "w") as quiet:
            async with stdio_client(params, errlog=quiet) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    return {t.name for t in listed.tools}

    names = await asyncio.wait_for(run(), timeout=60)
    assert names == set(mcp_server.CORE_TOOL_NAMES)
    assert len(names) == 7


def test_freellmapi_card_contract_and_retirement_guard():
    card = provider_catalog.card("freellmapi")
    assert card is not None
    assert card["kind"] == "openai"
    assert card["base_url"] == "http://127.0.0.1:3001/v1"
    assert card["model"] == "auto"
    assert card["key_mode"] == "required"
    assert card["key_url"] == "https://github.com/tashfeenahmed/freellmapi"
    assert card["editable_url"] is True
    assert card["caps"]["embeddings"] is True
    assert provider_catalog.guess_card("http://127.0.0.1:3001/v1") == "freellmapi"
    assert provider_catalog.guess_card("http://localhost:3001/v1") == "freellmapi"
    assert provider_catalog.guess_card("http://example.com:30010/v1") == "custom"
    assert provider_catalog.GROUP_BY_CARD["freellmapi"] == "paid"

    conn = ai_connections.create({
        "card": "freellmapi",
        "key": "freellmapi-test-unified-key-1234",
        "model": "custom/upstream-model",
    })
    assert ai_connections.replace_retired_model(conn.id, "custom/upstream-model") is None


@pytest.mark.parametrize(
    "argv,expected_key",
    [
        (["scan"], "ok"),
        (["list-provider-options"], "cards"),
        (["open-settings", "--card", "freellmapi", "--tab", "ai"], "url"),
        (["test-provider", "--service", "analysis"], "ok"),
        (["peek", "https://example.test/x"], "title"),
        (["ingest", "https://example.test/x"], "analysed"),
        (["import", "github_stars"], "imported"),
    ],
)
def test_setup_cli_awaits_every_async_subcommand_cleanly(monkeypatch, capsys, argv, expected_key):
    cli = _load_setup_cli()

    async def fake_scan():
        return {"ok": True, "version": "test"}

    async def fake_list_options():
        return {"cards": ["freellmapi"], "current": {"connections": []}}

    async def fake_test_provider(service, connection_id):
        return {"ok": True, "service": service, "connection_id": connection_id}

    async def fake_peek(url, max_chars):
        return {"ok": True, "title": url}

    async def fake_ingest(url):
        return {"ok": True, "analysed": True, "url": url}

    async def fake_import(*args):
        return {"ok": True, "imported": 0}

    monkeypatch.setattr(setup_flow, "scan", fake_scan)
    monkeypatch.setattr(setup_flow, "list_provider_options", fake_list_options)
    monkeypatch.setattr(setup_flow, "test_provider", fake_test_provider)
    monkeypatch.setattr(setup_flow, "peek", fake_peek)
    monkeypatch.setattr(setup_flow, "ingest", fake_ingest)
    monkeypatch.setattr(setup_flow, "import_data", fake_import)

    rc = cli.main(argv)
    out = capsys.readouterr().out
    assert rc == 0
    assert "coroutine" not in out
    parsed = json.loads(out)
    assert expected_key in parsed


def test_setup_cli_utf8_bom_file_and_stdin_and_error_exit_code(monkeypatch, tmp_path, capsys):
    cli = _load_setup_cli()

    # 1. PowerShell 5.1 UTF-8 BOM 檔案讀取
    bom_file = tmp_path / "answers_bom.json"
    bom_file.write_bytes(json.dumps({"about_you": "繁體中文測試工程師"}, ensure_ascii=False).encode("utf-8-sig"))
    loaded_file = cli._load_json_arg("", str(bom_file), "answers")
    assert loaded_file["about_you"] == "繁體中文測試工程師"

    # 2. UTF-8 bytes 經由 stdin 傳入不受 cp950 編碼破壞
    raw_bytes = json.dumps({"about_you": "繁體中文管線測試"}, ensure_ascii=False).encode("utf-8")
    fake_stdin = io.TextIOWrapper(io.BytesIO(raw_bytes), encoding="cp950")
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    loaded_stdin = cli._load_json_arg("-", "", "answers")
    assert loaded_stdin["about_you"] == "繁體中文管線測試"

    # 3. 失敗回傳（ok=false 或「錯誤：」字串）必回傳非 0 結束碼
    assert cli._dump({"ok": False, "error": "boom"}) == 1
    capsys.readouterr()
    assert cli._dump("錯誤：找不到項目") == 1
    capsys.readouterr()

    # 4. attach-diagram 子指令可把本機 HTML 存進收藏（免讀 API_KEY）
    item_id = database.save_item({"url": "https://github.com/acme/demo", "title_l1": "Demo"})
    html_file = tmp_path / "arch.html"
    html_file.write_text("<!doctype html><html><body><h1>Arch</h1></body></html>", encoding="utf-8")
    rc = cli.main(["attach-diagram", item_id, "--path", str(html_file)])
    out = capsys.readouterr().out
    assert rc == 0 and "已把架構圖存進收藏" in out
