"""Tiered MCP tool profiles (lean 7-tool core default), FreeLLMAPI card & setup_cli."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from app import ai_connections, mcp_server, provider_catalog

ROOT = Path(__file__).resolve().parents[1]


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
    mcp_server.configure_mcp_profile("review")
    assert _registered_tool_names() == set(mcp_server.CORE_TOOL_NAMES) | set(mcp_server.REVIEW_TOOL_NAMES)
    assert len(_registered_tool_names()) == 10

    mcp_server.configure_mcp_profile("setup")
    assert len(_registered_tool_names()) == 18
    assert set(mcp_server.SETUP_TOOL_NAMES) <= _registered_tool_names()

    mcp_server.configure_mcp_profile("core,review,labs")
    assert len(_registered_tool_names()) == 13

    mcp_server.configure_mcp_profile("full")
    assert len(_registered_tool_names()) == 29
    assert _registered_tool_names() == set(mcp_server.ALL_TOOL_FUNCTIONS)

    with pytest.raises(ValueError, match="不認得的 MCP profile"):
        mcp_server.configure_mcp_profile("nonexistent")


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
    assert card["key_mode"] == "optional"
    assert card["editable_url"] is True
    assert card["caps"]["embeddings"] is True
    assert provider_catalog.guess_card("http://127.0.0.1:3001/v1") == "freellmapi"
    assert provider_catalog.GROUP_BY_CARD["freellmapi"] == "paid"

    conn = ai_connections.create({"card": "freellmapi", "model": "custom/upstream-model"})
    assert ai_connections.replace_retired_model(conn.id, "custom/upstream-model") is None


def test_setup_cli_runs_open_settings_and_on_demand_without_full_mcp():
    import importlib.util

    spec = importlib.util.spec_from_file_location("setup_cli", ROOT / "scripts" / "setup_cli.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)

    out_open = asyncio.run(cli._dispatch(cli.build_parser().parse_args(["open-settings", "--card", "freellmapi", "--tab", "ai"])))
    assert "url" in out_open and "freellmapi" in out_open["url"]

    out_od = asyncio.run(cli._dispatch(cli.build_parser().parse_args(["on-demand", "nonexistent-tool-xyz"])))
    assert "找不到" in out_od or "尚未收錄" in out_od
