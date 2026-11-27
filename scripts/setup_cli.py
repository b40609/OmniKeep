"""CLI bridge for OmniKeep setup and evaluation workflows (0-token MCP companion).

When the MCP server runs on its lean default `core` profile (7 tools), the
`omnikeep-setup` and `omnikeep-review` skills can run first-time setup and
mobile evaluation closed-loop commands on demand through this CLI without
keeping 14+ low-frequency tool schemas loaded in every agent session.

All subcommands print UTF-8 JSON (or Markdown for text tools) and never expose
stored API keys or bot tokens.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        text = Path(file_path).read_text(encoding="utf-8")
    elif raw == "-":
        text = sys.stdin.read()
    elif raw:
        text = raw
    else:
        raise ValueError(f"缺少 {field_name}（請給 JSON 字串、'-' 由 stdin 讀入，或用檔案路徑參數）")
    return json.loads(text)


def _dump(payload: Any) -> int:
    if isinstance(payload, str):
        print(payload)
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


async def _dispatch(args: argparse.Namespace) -> Any:
    from app.app_settings import apply_overrides

    apply_overrides()

    cmd = args.command
    if cmd == "scan":
        from app import setup_flow
        return setup_flow.scan()
    if cmd == "peek":
        from app import setup_flow
        return await setup_flow.peek(args.url, args.max_chars)
    if cmd == "check-sources":
        from app import setup_flow
        sources = _load_json_arg(args.sources_json, args.sources_file, "sources")
        return await setup_flow.check_sources(sources, args.recent)
    if cmd == "list-provider-options":
        from app import setup_flow
        return setup_flow.list_provider_options()
    if cmd == "open-settings":
        from app import setup_flow
        return setup_flow.open_settings(args.card, args.tab)
    if cmd == "test-provider":
        from app import setup_flow
        return await setup_flow.test_provider(args.service, args.connection_id)
    if cmd == "preview-setup":
        from app import setup_flow
        answers = _load_json_arg(args.answers_json, args.answers_file, "answers")
        try:
            return await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": answers})
        except setup_flow.ServiceUnavailable:
            result = setup_flow.preview(answers)
            result["note"] = "OmniKeep 服務沒在跑：這是直接讀資料庫的預覽；套用前要先啟動服務"
            return result
        except setup_flow.ServiceError as exc:
            raise setup_flow.SetupError(str(exc)) from exc
    if cmd == "apply-setup":
        from app import setup_flow
        answers = _load_json_arg(args.answers_json, args.answers_file, "answers")
        return await setup_flow.call_service(
            "POST",
            "/api/setup/apply",
            json_body={"answers": answers, "confirm_code": args.confirm_code},
        )
    if cmd == "ingest":
        from app import setup_flow
        return await setup_flow.ingest(args.url)
    if cmd == "run-radar":
        from app import setup_flow
        return await setup_flow.call_service("POST", "/api/setup/run-radar", timeout=900.0)
    if cmd == "import":
        from app import setup_flow
        return await setup_flow.import_data(
            args.kind, args.path, args.browser, args.profile, args.enqueue_ai, args.limit
        )
    if cmd == "queue":
        from app.mcp_server import list_agent_queue
        return await list_agent_queue(status=args.status, limit=args.limit)
    if cmd == "decide":
        from app.mcp_server import record_agent_decision
        return await record_agent_decision(
            item_id=args.item_id,
            decision=args.decision,
            note=args.note,
            trigger_when=args.trigger_when,
        )
    if cmd == "on-demand":
        from app.mcp_server import search_on_demand_tools
        return await search_on_demand_tools(query=args.query, limit=args.limit)
    raise ValueError(f"不認得的子指令：{cmd}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OmniKeep 首次設定與評估閉環 CLI（免常駐 MCP schema）")
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

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(_dispatch(args))
        return _dump(result)
    except Exception as exc:
        from app import setup_flow
        if isinstance(exc, setup_flow.SetupError):
            _dump({"ok": False, "error": str(exc)})
            return 1
        _dump({"ok": False, "error": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
