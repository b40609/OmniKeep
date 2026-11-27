"""CLI bridge for OmniKeep setup, evaluation & diagram workflows (0-token MCP companion).

When the MCP server runs on its lean default `core` profile (7 tools), the
`omnikeep-setup` and `omnikeep-review` skills (and Archify diagram attach) can
run on demand through this CLI without keeping 15+ low-frequency tool schemas
loaded in every agent session.

All subcommands print UTF-8 JSON (or Markdown for text tools) and never expose
stored API keys or bot tokens.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
from pathlib import Path
from typing import Any, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _load_json_arg(raw: Optional[str], file_path: Optional[str], field_name: str) -> Any:
    if file_path:
        text = Path(file_path).read_text(encoding="utf-8-sig")
    elif raw == "-":
        # Always decode raw stdin bytes as UTF-8 (with optional BOM) to avoid Windows cp950 mojibake.
        text = sys.stdin.buffer.read().decode("utf-8-sig")
    elif raw:
        text = raw
    else:
        raise ValueError(f"缺少 {field_name}（請給 JSON 字串、'-' 由 stdin 讀入，或用檔案路徑參數）")
    return json.loads(text)


def _is_error_result(payload: Any) -> bool:
    if isinstance(payload, dict) and payload.get("ok") is False:
        return True
    if isinstance(payload, str) and (payload.startswith("錯誤：") or payload.startswith("❌")):
        return True
    return False


def _dump(payload: Any) -> int:
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 1 if _is_error_result(payload) else 0


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _dispatch(args: argparse.Namespace) -> Any:
    from app.app_settings import apply_overrides

    apply_overrides()

    cmd = args.command
    if cmd == "scan":
        from app import setup_flow
        result = setup_flow.scan()
    elif cmd == "peek":
        from app import setup_flow
        result = setup_flow.peek(args.url, args.max_chars)
    elif cmd == "check-sources":
        from app import setup_flow
        sources = _load_json_arg(args.sources_json, args.sources_file, "sources")
        result = setup_flow.check_sources(sources, args.recent)
    elif cmd == "list-provider-options":
        from app import setup_flow
        result = setup_flow.list_provider_options()
    elif cmd == "open-settings":
        from app import setup_flow
        result = setup_flow.open_settings(args.card, args.tab)
    elif cmd == "test-provider":
        from app import setup_flow
        result = setup_flow.test_provider(args.service, args.connection_id)
    elif cmd == "preview-setup":
        from app import setup_flow
        answers = _load_json_arg(args.answers_json, args.answers_file, "answers")
        try:
            result = await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": answers})
        except setup_flow.ServiceUnavailable:
            result = setup_flow.preview(answers)
            result["note"] = "OmniKeep 服務沒在跑：這是直接讀資料庫的預覽；套用前要先啟動服務"
        except setup_flow.ServiceError as exc:
            raise setup_flow.SetupError(str(exc)) from exc
    elif cmd == "apply-setup":
        from app import setup_flow
        answers = _load_json_arg(args.answers_json, args.answers_file, "answers")
        result = setup_flow.call_service(
            "POST",
            "/api/setup/apply",
            json_body={"answers": answers, "confirm_code": args.confirm_code},
        )
    elif cmd == "ingest":
        from app import setup_flow
        result = setup_flow.ingest(args.url)
    elif cmd == "run-radar":
        from app import setup_flow
        result = setup_flow.call_service("POST", "/api/setup/run-radar", timeout=900.0)
    elif cmd == "import":
        from app import setup_flow
        result = setup_flow.import_data(
            args.kind, args.path, args.browser, args.profile, args.enqueue_ai, args.limit
        )
    elif cmd == "queue":
        from app.mcp_server import list_agent_queue
        result = list_agent_queue(status=args.status, limit=args.limit)
    elif cmd == "decide":
        from app.mcp_server import record_agent_decision
        result = record_agent_decision(
            item_id=args.item_id,
            decision=args.decision,
            note=args.note,
            trigger_when=args.trigger_when,
        )
    elif cmd == "on-demand":
        from app.mcp_server import search_on_demand_tools
        result = search_on_demand_tools(query=args.query, limit=args.limit)
    elif cmd == "attach-diagram":
        from app.mcp_server import attach_item_diagram
        result = attach_item_diagram(item_id=args.item_id, path=args.path)
    elif cmd == "connect-freellmapi":
        bridge_mod = _load_freellmapi_bridge()
        slot_position = "prepend" if args.prepend else ("append" if args.append else None)
        result = bridge_mod.auto_connect(
            base_url=args.base_url,
            launch=args.launch,
            enable_keyless=not args.no_keyless,
            sync_existing_keys=args.sync_existing_keys,
            model=args.model,
            slot=args.slot,
            slot_position=slot_position,
            dry_run=args.dry_run,
        )
    else:
        raise ValueError(f"不認得的子指令：{cmd}")

    return await _maybe_await(result)


def _load_freellmapi_bridge():
    try:
        from scripts import freellmapi_bridge as mod
        return mod
    except ModuleNotFoundError:
        import importlib.util

        bridge_path = Path(__file__).resolve().parent / "freellmapi_bridge.py"
        spec = importlib.util.spec_from_file_location("omnikeep_freellmapi_bridge", bridge_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"找不到 FreeLLMAPI 接線腳本：{bridge_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OmniKeep 首次設定、評估閉環與架構圖 CLI（免常駐 MCP schema）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("scan", help="掃描硬體、OmniKeep 狀態、已接 AI 連線與書籤筆數")

    p_peek = sub.add_parser("peek", help="解析單一網址（不跑 AI、不存檔）")
    p_peek.add_argument("url")
    p_peek.add_argument("--max-chars", type=int, default=3000)

    p_check = sub.add_parser("check-sources", help="驗證候選探索來源（JSON 陣列）")
    p_check.add_argument("--sources-json", default="")
    p_check.add_argument("--sources-file", default="")
    p_check.add_argument("--recent", type=int, default=3)

    sub.add_parser("list-provider-options", help="列出 AI 服務選項卡片與目前連線")

    p_open = sub.add_parser("open-settings", help="取得設定頁連結（不讀寫金鑰）")
    p_open.add_argument("--card", default="")
    p_open.add_argument("--tab", default="ai")

    p_test = sub.add_parser("test-provider", help="測試已儲存的 AI 或頻道連線")
    p_test.add_argument("--service", default="analysis")
    p_test.add_argument("--connection-id", default="")

    p_prev = sub.add_parser("preview-setup", help="驗證設定答案 JSON 並產生預覽與確認碼")
    p_prev.add_argument("--answers-json", default="")
    p_prev.add_argument("--answers-file", default="")

    p_apply = sub.add_parser("apply-setup", help="以確認碼套用已核准的設定答案 JSON")
    p_apply.add_argument("--answers-json", default="")
    p_apply.add_argument("--answers-file", default="")
    p_apply.add_argument("--confirm-code", required=True)

    p_ingest = sub.add_parser("ingest", help="收藏並分析單一網址")
    p_ingest.add_argument("url")

    sub.add_parser("run-radar", help="執行一次探索巡檢並產出精選")

    p_imp = sub.add_parser("import", help="匯入書籤、GitHub 星標或 OPML")
    p_imp.add_argument("kind", choices=["bookmarks", "github_stars", "opml"])
    p_imp.add_argument("--path", default="")
    p_imp.add_argument("--browser", default="")
    p_imp.add_argument("--profile", default="")
    p_imp.add_argument("--enqueue-ai", action="store_true")
    p_imp.add_argument("--limit", type=int, default=1000)

    p_queue = sub.add_parser("queue", help="列出手機端工具評估佇列")
    p_queue.add_argument("--status", default="needs_decision")
    p_queue.add_argument("--limit", type=int, default=20)

    p_dec = sub.add_parser("decide", help="回寫工具評估最終判定")
    p_dec.add_argument("item_id")
    p_dec.add_argument("decision")
    p_dec.add_argument("--note", default="")
    p_dec.add_argument("--trigger-when", default="")

    p_od = sub.add_parser("on-demand", help="依關鍵字動態召回情境備案工具（on_demand）")
    p_od.add_argument("query", nargs="?", default="")
    p_od.add_argument("--limit", type=int, default=5)

    p_diag = sub.add_parser("attach-diagram", help="把本機 Archify 產出的架構圖 HTML 存進收藏")
    p_diag.add_argument("item_id")
    p_diag.add_argument("--path", required=True, help="獨立 HTML 檔案的絕對路徑")

    p_flm = sub.add_parser("connect-freellmapi", help="一鍵免手動貼上接線本機 FreeLLMAPI 桌面版")
    _load_freellmapi_bridge().add_bridge_arguments(p_flm)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_dispatch(args))
        return _dump(result)
    except Exception as exc:
        _dump({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
