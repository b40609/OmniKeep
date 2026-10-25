import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from app.database import (
    init_db,
    add_watch_target,
    get_watch_target,
    get_watch_targets,
    update_watch_target,
    delete_watch_target,
    save_proposal,
    get_proposals,
    decide_proposal,
    get_item_by_id,
    get_backup_runs,
)
from app.watch.redact import redact_text, is_risky_filename, find_risky_files
from app.watch.scanner import scan_target
from app.backup import run_backup

# pytest's tmp_path fixture hits PermissionError on this machine's
# pytest-of-user temp root, so tests roll their own dirs under the project.
_TMP_ROOT = Path(__file__).parent / ".tmp"


def _tmpdir() -> Path:
    _TMP_ROOT.mkdir(exist_ok=True)
    d = Path(tempfile.mkdtemp(dir=str(_TMP_ROOT), prefix=f"ok-{uuid.uuid4().hex[:6]}-"))
    return d


def setup_module(module):
    init_db()


# ── Secret redaction layer ──────────────────────────────────────

def test_redact_text_catches_common_credential_formats():
    text = (
        "OPENAI_API_KEY=sk-abcdef1234567890abcdef1234567890abcdef12\n"
        "github: ghp_" + "A" * 36 + "\n"
        "aws: AKIAIOSFODNN7EXAMPLE\n"
        "slack: xoxb-1234567890-abcdefghijklmn\n"
        "key = -----BEGIN RSA PRIVATE KEY-----\n"
        "okx_secret: 7fJk29dkaQWERTYUIOpz123\n"
    )
    out = redact_text(text)
    assert "sk-abcdef" not in out
    assert "ghp_" + "A" * 36 not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert "xoxb-1234567890" not in out
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "7fJk29dkaQWERTYUIOpz123" not in out
    assert out.count("[REDACTED:") >= 6


def test_redact_text_keeps_harmless_text():
    clean = "這個專案用 FastAPI + SQLite，token 化的詞不等於機密，secret 架構是分層設計。"
    assert redact_text(clean) == clean


def test_risky_filename_detection():
    risky = ["OKX_API.txt", "Password.txt", "Kimi_K3_API_Keys.csv", "id_rsa",
             ".env", "server.pem", "my_wallet_backup.dat", "api_key.json",
             "binance_key.txt"]
    safe = ["README.md", "requirements.txt", "main.py", "token_bucket.py",
            "secret_architecture_notes.txt", "okx_client.py", ".env.example",
            "okx-readonly-contract.md", "docs/evidence/okx-demo-subtypes.json"]
    for name in risky:
        assert is_risky_filename(name), name
    for name in safe:
        assert not is_risky_filename(name), name


def test_find_risky_files_filters_list():
    files = ["README.md", "OKX_API.txt", "src/main.py", "Password.txt"]
    assert find_risky_files(files) == ["OKX_API.txt", "Password.txt"]


# ── Watch targets & proposals DAO ───────────────────────────────

def test_watch_target_crud_roundtrip():
    d = _tmpdir()
    try:
        name = f"test-target-{uuid.uuid4().hex[:6]}"
        t = add_watch_target(name, str(d), "folder", "open")
        assert t["read_scope"]["code"] is True          # open preset = all on
        assert t["outbound_consent"]["git"] is True

        assert get_watch_target(t["id"])["name"] == name

        updated = update_watch_target(t["id"], {"read_scope": {"filenames": True}})
        assert updated["read_scope"]["filenames"] is True
        assert updated["read_scope"]["code"] is False   # full map replaced

        assert delete_watch_target(t["id"]) is True
        assert get_watch_target(t["id"]) is None
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_proposal_dedup_and_decision_flow():
    d = _tmpdir()
    try:
        t = add_watch_target(f"p-{uuid.uuid4().hex[:6]}", str(d), "folder", "open")
        dedup = f"risk:{t['id']}:{uuid.uuid4().hex[:6]}"
        item_id = f"item-{uuid.uuid4().hex[:6]}"

        first = save_proposal({"item_id": item_id, "target_id": t["id"],
                               "proposal_type": "risk", "impact": 8, "confidence": 9,
                               "effort": 2, "dedup_key": dedup})
        assert first is not None
        assert save_proposal({"item_id": item_id, "dedup_key": dedup}) is None  # 30-day dedup

        decided = decide_proposal(first["id"], "dismissed",
                                  corrections={"impact": 3}, reason="太誇張")
        assert decided["status"] == "dismissed"
        assert decided["user_impact"] == 3.0
        assert decided["impact"] == 8.0                  # AI prior preserved
        delete_watch_target(t["id"])                     # don't pollute real DB
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── Scanner (L0 risk + local-only fingerprint, no cloud calls) ──

@pytest.mark.asyncio
async def test_scan_target_local_only_fingerprint_and_risk():
    d = _tmpdir()
    try:
        (d / "README.md").write_text("# Demo\nBacktesting demo project.", encoding="utf-8")
        (d / "requirements.txt").write_text("fastapi==0.110\n", encoding="utf-8")
        (d / "OKX_API.txt").write_text("should never be read", encoding="utf-8")
        (d / "app.py").write_text("print('hi')", encoding="utf-8")

        t = add_watch_target(f"scan-{uuid.uuid4().hex[:6]}", str(d), "folder", "custom",
                             read_scope={"filenames": True, "readme": True, "deps": True,
                                         "code": False, "git": False},
                             outbound_consent={"summary": False, "docs": False, "deps": False,
                                               "code": False, "git": False})
        result = await scan_target(get_watch_target(t["id"]))
        assert result["ok"] is True
        assert result["risk_proposal"] is True           # OKX_API.txt caught by filename
        assert result["fingerprint_updated"] is True

        props = [p for p in get_proposals(status="pending") if p["target_id"] == t["id"]]
        assert len(props) == 1
        card = get_item_by_id(props[0]["item_id"])
        assert card["category_name"] == "提案"
        # secret file CONTENT must never appear in the proposal card
        assert "should never be read" not in (card["deep_analysis"] or "")

        fp = get_item_by_id(result["fingerprint_item_id"])
        assert fp["category_name"] == "監看"
        assert "本地統計" in fp["title_l1"]               # no-cloud path

        result2 = await scan_target(get_watch_target(t["id"]))
        assert result2["changed"] is False               # unchanged tree → skip
        assert result2["fingerprint_updated"] is False
        delete_watch_target(t["id"])                     # don't pollute real DB
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── Multi-sink backup (local rotation) ──────────────────────────

def test_backup_local_sink_rotates(monkeypatch):
    from app.config import settings
    d = _tmpdir()
    backup_dir = d / "backups"
    monkeypatch.setattr(settings, "BACKUP_SINK", "local")
    monkeypatch.setattr(settings, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setattr(settings, "BACKUP_KEEP", 2)

    assert run_backup()["status"] == "ok"
    assert run_backup()["status"] == "ok"
    assert run_backup()["status"] == "ok"

    zips = sorted(backup_dir.glob("omnikeep-backup-*.zip"))
    assert len(zips) == 2                                # rotated to BACKUP_KEEP
    assert all(z.stat().st_size > 0 for z in zips)

    runs = get_backup_runs(limit=5)
    assert len(runs) >= 3 and runs[0]["status"] == "ok"
    shutil.rmtree(d, ignore_errors=True)


def test_backup_off_sink_skips(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "BACKUP_SINK", "off")
    assert run_backup()["status"] == "skipped"
