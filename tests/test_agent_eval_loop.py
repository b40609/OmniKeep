"""End-to-end verification of P1-P4 mobile Agent evaluation loop (Track A)."""
from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import mcp_server, pipeline, push
from app.bot.telegram_bot import TelegramBot
from app.config import settings
from app.database import (
    find_item_by_canonical_or_url,
    get_db_connection,
    get_item_by_id,
    get_items,
    get_status_counts,
    init_db,
    save_item,
)
from app.eval.adapter import LocalLiteAdapter, OmniKitAdapter, get_evaluator_adapter
from app.eval.runner import enqueue_evaluation_for_item, run_evaluation
from app.eval.security import (
    BADGE_EXECUTABLE,
    BADGE_PASS,
    BADGE_RISK,
    classify_security_badge,
)
from app.eval.store import get_evaluation, get_evaluation_counts, list_evaluations
from app.main import app
from app.queue.worker import TaskWorker

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}


def test_db_migration_is_idempotent_and_counts_exclude_merged():
    # Calling init_db twice on an existing DB succeeds without data loss.
    init_db()
    init_db()

    with closing(get_db_connection()) as conn:
        item_cols = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
        task_cols = {r[1] for r in conn.execute("PRAGMA table_info(ingest_tasks)").fetchall()}
        eval_table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='item_evaluations'"
        ).fetchone()

    assert {"user_note", "intent", "eval_track", "agent_status", "merged_into_id", "community_counterpoints"} <= item_cols
    assert {"user_note", "intent", "target_project"} <= task_cols
    assert eval_table is not None

    parent_id = save_item({
        "url": "https://github.com/example/parent-tool",
        "source_type": "web",
        "title_l1": "父卡工具",
        "summary_l1": "主卡",
        "tech_tags": ["Agent"],
        "user_note": "看能不能省 token",
        "intent": "agent_eval",
        "agent_status": "needs_decision",
        "community_counterpoints": [{"point": "依賴 Python 3.12", "category": "limitation", "source": "x_reply"}],
    })
    save_item({
        "url": "https://x.com/user/status/999",
        "source_type": "web",
        "title_l1": "被合併子卡",
        "summary_l1": "不該出現在清單",
        "tech_tags": [],
        "merged_into_id": parent_id,
    })

    listed = get_items(is_read=False)
    listed_ids = {i["id"] for i in listed}
    assert parent_id in listed_ids
    assert all(i["merged_into_id"] == "" for i in listed)
    assert get_item_by_id(parent_id)["community_counterpoints"][0]["point"] == "依賴 Python 3.12"
    assert get_status_counts()["inbox"] == 1


def test_three_state_security_badge_never_false_greens_cli_repos():
    # 0 SKILL.md found (like fast-anything CLI/MCP) -> amber executable_needs_review, NOT green.
    assert classify_security_badge({"skills_found": 0}, repo_files=["package.json", "Cargo.toml", "src/main.rs"]) == BADGE_EXECUTABLE
    # Even if a repo has a SKILL.md, having executable artifacts flags executable_needs_review.
    assert classify_security_badge({"skills_found": 1}, repo_files=["SKILL.md", "scripts/install.sh"]) == BADGE_EXECUTABLE
    # Pure SKILL.md without executable code -> green pass.
    assert classify_security_badge({"skills_found": 1}, repo_files=["skills/demo/SKILL.md", "README.md"]) == BADGE_PASS
    # High risk findings or failed security verdict -> red risk_flagged.
    assert classify_security_badge({"skills_found": 1, "high_risk_findings": ["exfil"]}, repo_files=["SKILL.md"]) == BADGE_RISK
    assert classify_security_badge({"skills_found": 1}, verdict="fail") == BADGE_RISK


@pytest.mark.asyncio
async def test_pipeline_injects_user_note_merges_single_repo_social_post_and_keeps_counterpoints(monkeypatch):
    captured_prompts = []

    class FakeProvider:
        async def generate_json(self, prompt, system_prompt):
            captured_prompts.append(prompt)
            return {
                "category": "開源專案",
                "title_l1": "fast-anything：把多來源資料轉成 Agent 記憶",
                "summary_l1": "用 CLI 與 MCP 把文件轉換成結構化上下文，支援 npm 與 Cargo 安裝。",
                "tech_tags": ["MCP", "Rust", "Agent"],
                "deep_analysis": "> 值得對照現有搜尋前置作業。\n\n## 最重要的 3 件事\n- **用途**：快速轉換\n- **差異**：Rust 實作\n- **安裝**：npm / cargo\n\n## 我可以怎麼用\n- 先檢視依賴",
                "is_composite": False,
                "sub_entities": [
                    {
                        "name": "EL4CTEO/fast-anything",
                        "canonical_url": "https://github.com/EL4CTEO/fast-anything",
                        "reason": "作者一樓附上的開源倉庫",
                        "status": "verified",
                    }
                ],
                "community_counterpoints": [
                    {"point": "留言提醒 Windows 本機編譯需要 Rust toolchain", "category": "limitation", "source": "x_reply"}
                ],
            }

    x_page = {
        "url": "https://x.com/mingzi206/status/2124437302068011026",
        "title": "mingzi206 推薦 fast-anything",
        "author": "@mingzi206",
        "content_raw": "正文推薦專案\n\n作者一樓：https://github.com/EL4CTEO/fast-anything\n\n留言回覆：Windows 編譯要裝 Rust",
        "cover_image": "",
        "raw_html": "",
        "http_status": 200,
    }
    spawned_children = []
    monkeypatch.setattr(pipeline, "parse_web_page", AsyncMock(return_value=x_page))
    monkeypatch.setattr(pipeline, "get_primary_provider", lambda: FakeProvider())
    monkeypatch.setattr("app.research.competitor_detector.detect_competitors_and_alternatives", AsyncMock())
    monkeypatch.setattr(
        "app.background.follow_up_pool.submit",
        lambda fn: spawned_children.append(fn) or True,
    )

    saved = await pipeline.run_pipeline(
        "https://x.com/mingzi206/status/2124437302068011026",
        user_note="看是否能取代現有前處理腳本",
        intent="agent_eval",
    )

    # 1. user_note actually reached normal web/X analysis prompt!
    assert len(captured_prompts) == 1
    assert "<user_note>" in captured_prompts[0]
    assert "看是否能取代現有前處理腳本" in captured_prompts[0]
    assert "community_counterpoints" in captured_prompts[0]

    # 2. Single-card merge: only 1 item in DB, anchored on GitHub canonical URL, no duplicate child spawned.
    assert spawned_children == []
    assert saved["url"] == "https://github.com/el4cteo/fast-anything"
    assert saved["user_note"] == "看是否能取代現有前處理腳本"
    assert saved["intent"] == "agent_eval"
    assert saved["agent_status"] == "queued"
    assert "## 原社群貼文與討論附錄" in saved["content_raw"]
    assert saved["community_counterpoints"][0]["category"] == "limitation"

    all_items = get_items(is_read=None)
    assert len(all_items) == 1

    # 3. Re-saving another tweet about the same repo updates the existing card instead of splitting.
    x_page_2 = {
        **x_page,
        "url": "https://x.com/other/status/999999",
        "author": "@other",
        "content_raw": "另一位網友實測心得",
    }
    monkeypatch.setattr(pipeline, "parse_web_page", AsyncMock(return_value=x_page_2))
    saved_2 = await pipeline.run_pipeline(
        "https://x.com/other/status/999999",
        user_note="追問 Windows 相容性",
        intent="agent_eval",
    )
    assert saved_2["id"] == saved["id"]
    assert len(get_items(is_read=None)) == 1
    assert "https://x.com/other/status/999999" in saved_2["content_raw"]


@pytest.mark.asyncio
async def test_omnikit_adapter_subprocess_contract_and_fallback(tmp_path, monkeypatch):
    # Create fake OmniKit scripts in tmp_path
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True)
    eval_log = tmp_path / "seen_eval.json"
    dec_log = tmp_path / "seen_decision.json"

    (scripts_dir / "eval_single.py").write_text(
        f"""
import json, pathlib, sys
req = json.loads(sys.stdin.read())
pathlib.Path({str(eval_log)!r}).write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
out = {{
    "schema_version": "1.0",
    "status": "ok",
    "security_badge": "executable_needs_review",
    "layer0": {{
        "layer": 0,
        "repo": req["target_repo"],
        "url": req["target_url"],
        "github": {{"stars": 2301, "license": "MIT", "pushed_at": "2026-11-23T01:00:00Z"}},
        "scan": {{"skills_found": 0, "executable_artifacts": ["Cargo.toml"]}},
        "verdict": "warn"
    }},
    "layer1": {{
        "layer": 1,
        "tool_id": "fast-anything",
        "name": "fast-anything",
        "url": req["target_url"],
        "slots": ["search_ingestion"],
        "scenarios": ["大量檔案轉純文字"],
        "summary": "針對你的問題：可加快轉檔，但需測試 Windows Rust 依賴。",
        "claims": [{{"claim": "速度快 3 倍", "kind": "performance", "how_to_verify": "用 10 份樣本實測"}}],
        "recommendation": "deep_eval"
    }},
    "slot_comparison": {{
        "matched_slots": ["search_ingestion"],
        "incumbent_tools": ["local_parser"],
        "delta_summary": "現任已覆蓋七成，實測效能成立再考慮導入。"
    }},
    "suggested_action": "approve_l2",
    "error": ""
}}
print(json.dumps(out, ensure_ascii=False))
""",
        encoding="utf-8",
    )
    (scripts_dir / "record_decision.py").write_text(
        f"""
import json, pathlib, sys
req = json.loads(sys.stdin.read())
pathlib.Path({str(dec_log)!r}).write_text(json.dumps(req, ensure_ascii=False), encoding="utf-8")
print(json.dumps({{"ok": True, "decision": req["decision"]}}))
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "OMNIKIT_REPO_PATH", str(tmp_path))
    adapter = get_evaluator_adapter()
    assert isinstance(adapter, OmniKitAdapter)

    item_id = save_item({
        "url": "https://github.com/EL4CTEO/fast-anything",
        "source_type": "web",
        "title_l1": "fast-anything",
        "summary_l1": "快速轉檔工具",
        "tech_tags": ["Rust"],
        "user_note": "值不值得換掉舊轉換腳本",
        "intent": "agent_eval",
        "community_counterpoints": [{"point": "依賴本機 toolchain", "category": "limitation", "source": "x_reply"}],
    })

    # Verify evaluation pushes deep link /?open=eval:<id>
    sent_pushes = []
    monkeypatch.setattr(
        push,
        "send_push",
        AsyncMock(side_effect=lambda title, body, url="/", tag=None: sent_pushes.append((title, body, url, tag)) or {"sent": 1, "removed": 0, "failed": 0}),
    )

    ev = enqueue_evaluation_for_item(item_id, run_in_background=False)
    finished = await run_evaluation(ev["id"])

    assert finished["status"] == "ready"
    assert finished["security_badge"] == BADGE_EXECUTABLE
    assert finished["adapter"] == "omnikit"
    assert get_item_by_id(item_id)["agent_status"] == "needs_decision"

    seen_req = json.loads(eval_log.read_text(encoding="utf-8"))
    assert seen_req["max_layer"] == 1  # Safety red line
    assert seen_req["user_note"] == "值不值得換掉舊轉換腳本"
    assert seen_req["community_counterpoints"][0]["category"] == "limitation"

    assert len(sent_pushes) == 1
    assert sent_pushes[0][2] == f"/?open=eval:{ev['id']}"

    # Decide approve_l2 -> populates l2_request + triggers OmniKit writeback
    with TestClient(app) as client:
        res_list = client.get("/api/evaluations?status=needs_decision", headers=HEADERS)
        assert res_list.status_code == 200
        assert res_list.json()["counts"]["needs_decision"] == 1

        res_dec = client.post(
            f"/api/evaluations/{ev['id']}/decide",
            headers=HEADERS,
            json={"decision": "approve_l2", "note": "週末測試十份 PDF"},
        )
        assert res_dec.status_code == 200
        body = res_dec.json()
        assert body["evaluation"]["decision"] == "approve_l2"
        assert body["evaluation"]["l2_request"]["source"] == "omnikeep_mobile_approval"
        assert body["writeback"]["synced"] is True
        assert get_item_by_id(item_id)["agent_status"] == "approved_l2"

    seen_dec = json.loads(dec_log.read_text(encoding="utf-8"))
    assert seen_dec["decision"] == "approve_l2"
    assert seen_dec["target_repo"] == "EL4CTEO/fast-anything"

    # Without OmniKit path, falls back gracefully to LocalLiteAdapter
    monkeypatch.setattr(settings, "OMNIKIT_REPO_PATH", "")
    monkeypatch.delenv("OMNIKIT_REPO_PATH", raising=False)
    assert isinstance(get_evaluator_adapter(), LocalLiteAdapter)


@pytest.mark.asyncio
async def test_mcp_bugfix_new_tools_and_telegram_eval(monkeypatch):
    # 1. writeback_insight writes once on new item
    save_calls = []
    orig_save = mcp_server.save_item

    def counting_save(data):
        save_calls.append(data["title_l1"])
        return orig_save(data)

    monkeypatch.setattr(mcp_server, "save_item", counting_save)
    res_wb = await mcp_server.writeback_insight(
        title="單次寫入檢查",
        summary="確認不會呼叫兩次 save_item",
        architecture_details="詳細架構",
    )
    assert "✅" in res_wb
    assert save_calls == ["單次寫入檢查"]

    # 2. Prepare an item and run local_lite sync evaluation via API
    item_id = orig_save({
        "url": "https://github.com/demo/context-helper",
        "source_type": "web",
        "title_l1": "context-helper",
        "summary_l1": "按需壓縮長上下文",
        "tech_tags": ["MCP", "Context"],
        "user_note": "只有大專案才用得到",
        "content_raw": "X" * 3500 + "\nTAIL_MARKER_PRESERVED",
        "community_counterpoints": [{"point": "高記憶體需求", "category": "cost", "source": "x_reply"}],
    })

    # Stub GitHub network calls inside LocalLiteAdapter so test stays offline
    monkeypatch.setattr("app.eval.adapter.fetch_repo", AsyncMock(return_value={"paths": ["package.json", "src/index.ts"]}))
    monkeypatch.setattr(LocalLiteAdapter, "_fetch_github_meta", AsyncMock(return_value={"stars": 500, "license": "MIT"}))
    monkeypatch.setattr(settings, "OMNIKIT_REPO_PATH", "")

    with TestClient(app) as client:
        eval_res = client.post(
            f"/api/items/{item_id}/evaluate",
            headers=HEADERS,
            json={"sync": True},
        )
        assert eval_res.status_code == 200
        ev_id = eval_res.json()["evaluation"]["id"]

        item_detail = client.get(f"/api/items/{item_id}", headers=HEADERS).json()
        assert item_detail["latest_evaluation"]["id"] == ev_id

    # Verify get_item_detail preserves past 2000 chars up to default 8000
    detail_text = await mcp_server.get_item_detail(item_id, include_raw=True)
    assert "TAIL_MARKER_PRESERVED" in detail_text
    assert "使用者備註" in detail_text
    assert "社群實測與反例" in detail_text

    # list_agent_queue sees needs_decision
    q_text = await mcp_server.list_agent_queue(status="needs_decision")
    assert item_id in q_text

    # record_agent_decision -> on_demand + Progressive Disclosure recall
    rec_text = await mcp_server.record_agent_decision(
        item_id=item_id,
        decision="on_demand",
        note="大上下文才啟用",
        trigger_when="超過 100 檔案的大型重構需要壓縮上下文",
    )
    assert "on_demand" in rec_text

    recall = await mcp_server.search_on_demand_tools(query="大型重構")
    assert item_id in recall
    assert "超過 100 檔案的大型重構" in recall

    # 3. Telegram /eval fallback command creates agent_eval task
    bot = TelegramBot(token="123456:test-token")
    bot.is_authorized = MagicMock(return_value=True)
    bot.send_message = AsyncMock()
    await bot.handle_update({
        "update_id": 888,
        "message": {
            "message_id": 99,
            "chat": {"id": 12345},
            "from": {"id": 12345},
            "text": "/eval https://github.com/demo/context-helper 確認相容性",
        },
    })
    with closing(get_db_connection()) as conn:
        row = conn.execute(
            "SELECT url, user_note, intent FROM ingest_tasks WHERE chat_id = '12345' OR chat_id = 12345"
        ).fetchone()
    assert row is not None
    assert row["url"] == "https://github.com/demo/context-helper"
    assert row["intent"] == "agent_eval"
    assert row["user_note"] == "確認相容性"


@pytest.mark.asyncio
async def test_worker_carries_eval_intent_and_enqueues_evaluation(monkeypatch):
    submitted = []
    monkeypatch.setattr(
        "app.background.follow_up_pool.submit",
        lambda fn: submitted.append(fn) or True,
    )
    fake_item_id = save_item({
        "url": "https://github.com/existing/eval-target",
        "source_type": "web",
        "title_l1": "existing target",
        "summary_l1": "已存在項目",
        "tech_tags": ["AI"],
    })
    worker = TaskWorker()
    await worker._process_task({
        "id": "task_eval_hit",
        "url": "https://github.com/existing/eval-target",
        "source": "api",
        "user_note": "補充新疑慮",
        "intent": "agent_eval",
        "target_project": "",
    })
    updated = get_item_by_id(fake_item_id)
    assert updated["intent"] == "agent_eval"
    assert updated["user_note"] == "補充新疑慮"
    assert updated["agent_status"] == "queued"
    assert len(submitted) == 1
    assert get_evaluation_counts()["evaluating"] == 1
    assert len(list_evaluations("evaluating")) == 1
