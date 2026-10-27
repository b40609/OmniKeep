"""Security, transaction and lifecycle regressions from the October audit.

All credentials and documents here are synthetic; conftest isolates storage
and disables external sockets before any application request is made.
"""
import asyncio
import base64
import socket
import sqlite3
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import backup, database as db, network
from app.background import FollowUpPool
from app.config import settings
from app.file_lock import FileLock
from app.main import app
from app.queue.worker import TaskWorker
from app.static_assets import CurrentBuildFiles
from app.watch import scanner, relevance
from app.watch.redact import redact_text, is_risky_filename


def item(name="card", **extra):
    return db.save_item({"url": f"https://fixture.invalid/{name}",
                         "title_l1": name, "origin": "radar", "tech_tags": ["Python"], **extra})


def execute(sql, args=()):
    with closing(db.get_db_connection()) as conn, conn:
        return conn.execute(sql, args).fetchall()


def headers():
    return {"Authorization": f"Bearer {settings.API_KEY}"}


@pytest.mark.parametrize("path", ["/api/items", "/api/watch/targets", "/api/behavior/deck",
                                     "/mcp", "/mcp/sse", "/mcp/messages/",
                                     "/mcp%2Fsse", "/api%2Fwatch/targets"])
def test_all_private_routes_require_header(path):
    with TestClient(app) as client:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 401
        assert response.headers["cache-control"] == "no-store"


def test_auth_and_cors_fail_closed(monkeypatch):
    with TestClient(app) as client:
        assert client.get("/health").json() == {
            "status": "healthy", "service": "OmniKeep", "version": "0.1.0"}
        assert client.get("/api/watch/targets", headers=headers()).status_code == 200
        assert client.get("/api/watch/targets", headers={"X-API-Key": settings.API_KEY}).status_code == 200
        assert client.get("/api/watch/targets", params={"token": settings.API_KEY}).status_code == 401
        preflight = client.options("/api/watch/targets", headers={
            "Origin": "https://hostile.invalid", "Access-Control-Request-Method": "GET"})
        assert preflight.status_code == 400
        assert "access-control-allow-origin" not in preflight.headers
        monkeypatch.setattr(settings, "API_KEY", "weak-test-key")
        response = client.get("/api/watch/targets", headers=headers())
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"


def test_only_current_static_build_is_served(isolated_runtime):
    root = isolated_runtime / "static"
    (root / "dist/assets").mkdir(parents=True)
    (root / "dist/index.html").write_text('<script src="/static/dist/assets/current.js"></script>')
    for name in ("current.js", "retired.js"):
        (root / "dist/assets" / name).write_text("// synthetic bundle")
    (root / "dist/favicon.svg").write_text("<svg/>")
    (root / "legacy.html").write_text("synthetic legacy UI")
    (root / "mobile_test.html").write_text("synthetic archived mobile test")
    (root / "qr_webhook_public.png").write_bytes(b"synthetic legacy credential QR")
    test_app = FastAPI()
    test_app.mount("/static", CurrentBuildFiles(directory=root))
    with TestClient(test_app) as client:
        assert client.get("/static/dist/assets/current.js").status_code == 200
        assert client.get("/static/dist/assets/retired.js").status_code == 404
        assert client.get("/static/legacy.html").status_code == 404
        assert client.get("/static/mobile_test.html").status_code == 404
        assert client.get("/static/qr_webhook_public.png").status_code == 404
        assert client.get("/static/dist/favicon.svg").status_code == 200
        assert client.get("/static/dist/index.html").headers["cache-control"] == "no-cache"


@pytest.mark.parametrize("url", [
    "http://127.0.0.1", "https://10.0.0.1", "http://169.254.169.254/latest",
    "http://[::1]", "http://[::ffff:8.8.8.8]", "http://[ff02::1]",
    "http://localhost", "file:///etc/passwd", "http://user:pass@example.com",
    "https://example.com:9222", "http://127%2e0%2e0%2e1",
])
def test_reject_nonpublic_url_forms(url):
    with pytest.raises(network.UnsafeURL):
        network.validate_url(url)


@pytest.mark.asyncio
async def test_dns_validation_pins_address_and_rejects_mixed_answers(monkeypatch):
    def answers(*ips):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]

    backend = network.PublicNetworkBackend()
    backend.backend = Mock(connect_tcp=AsyncMock(return_value="stream"))
    resolve = Mock(return_value=answers("8.8.8.8"))
    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    assert await backend.connect_tcp("public.invalid", 443) == "stream"
    assert resolve.call_count == 1
    assert backend.backend.connect_tcp.call_args.args[:2] == ("8.8.8.8", 443)
    resolve.return_value = answers("8.8.8.8", "127.0.0.1")
    backend.backend.connect_tcp.reset_mock()
    with pytest.raises(network.UnsafeURL):
        await backend.connect_tcp("rebound.invalid", 443)
    backend.backend.connect_tcp.assert_not_called()
    sync = network.PublicSyncBackend()
    with pytest.raises(network.UnsafeURL):
        sync.connect_tcp("rebound.invalid", 443)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["async", "sync"])
async def test_pinned_https_keeps_original_tls_server_name(monkeypatch, mode):
    class Stream:
        def __init__(self):
            self.server_hostname = None
            self.response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"

        def read(self, max_bytes, timeout=None):
            response, self.response = self.response, b""
            return response

        def write(self, buffer, timeout=None):
            pass

        def close(self):
            pass

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            self.server_hostname = server_hostname
            return self

        def get_extra_info(self, info):
            return None

    class AsyncStream(Stream):
        async def read(self, max_bytes, timeout=None):
            return super().read(max_bytes, timeout)

        async def write(self, buffer, timeout=None):
            pass

        async def aclose(self):
            pass

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            return super().start_tls(ssl_context, server_hostname, timeout)

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))])
    if mode == "async":
        stream = AsyncStream()
        connect = AsyncMock(return_value=stream)
        monkeypatch.setattr(network, "AutoBackend", lambda: Mock(connect_tcp=connect))
        async with network.public_http_client() as client:
            response = await client.get("https://public.invalid/check")
    else:
        stream = Stream()
        connect = Mock(return_value=stream)
        monkeypatch.setattr(network, "SyncBackend", lambda: Mock(connect_tcp=connect))
        with network.public_sync_client() as client:
            response = client.get("https://public.invalid/check")
    assert response.status_code == 200 and response.text == "ok"
    assert connect.call_args.args[:2] == ("8.8.8.8", 443)
    assert stream.server_hostname == "public.invalid"


@pytest.mark.asyncio
async def test_redirect_is_validated_before_second_request(monkeypatch):
    contacted = []

    async def respond(request):
        contacted.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    monkeypatch.setattr(network, "PublicHTTPTransport", lambda: httpx.MockTransport(respond))
    async with network.public_http_client(follow_redirects=True) as client:
        with pytest.raises(network.UnsafeURL):
            await client.get("https://public.invalid/start")
    assert contacted == ["https://public.invalid/start"]


def test_media_transport_preserves_ytdlp_response_contract(monkeypatch):
    from app.parsers import media_network
    from yt_dlp.networking import Request
    from yt_dlp.networking.exceptions import HTTPError

    monkeypatch.setattr(media_network, "public_sync_client", lambda **kwargs: httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b"media"))))
    with media_network.PublicYoutubeDL({"quiet": True, "no_warnings": True}) as downloader:
        response = downloader.urlopen(Request("https://media.invalid/clip"))
        assert response.read() == b"media"
        assert response.status == 200
        assert response.headers["Content-Length"] == "5"
        response.close()
        with pytest.raises(network.UnsafeURL):
            downloader.urlopen("http://127.0.0.1/private")
        monkeypatch.setattr(media_network, "public_sync_client", lambda **kwargs: httpx.Client(
            transport=httpx.MockTransport(lambda req: httpx.Response(403, content=b"denied"))))
        with pytest.raises(HTTPError):
            downloader.urlopen("https://media.invalid/denied")


def test_redaction_handles_encodings_fragments_and_private_blocks():
    synthetic = "sK-" + "SyntheticTestValue" * 3
    encoded = base64.b64encode(synthetic.encode()).decode()
    wrapped = "\n".join(encoded[i:i + 24] for i in range(0, len(encoded), 24))
    cases = [synthetic, quote(synthetic, safe=""),
             "".join(f"\\u{ord(c):04x}" for c in synthetic),
             synthetic[:15] + '" + "' + synthetic[15:],
             synthetic[:15] + "\\\n" + synthetic[15:], encoded, wrapped,
             base64.b64encode(encoded.encode()).decode(),
             "-----BEGIN RSA PRIVATE KEY-----\nSYNTHETIC_BODY\n-----END RSA PRIVATE KEY-----"]
    for value in cases:
        assert "[REDACTED:" in redact_text(value)
    assert redact_text(wrapped) == "[REDACTED:encoded]"
    assert redact_text("FastAPI + SQLite") == "FastAPI + SQLite"
    assert is_risky_filename(".env.production")
    assert is_risky_filename("id_ed25519")
    assert not is_risky_filename(".env.example")


def test_dedup_and_snooze_use_elapsed_time_not_lexical_dates():
    card = item()
    proposal = db.save_proposal({"item_id": card, "dedup_key": "elapsed"})
    now = datetime.now(timezone.utc)
    execute("UPDATE proposals SET created_at = ? WHERE id = ?",
            ((now - timedelta(days=30, minutes=5)).isoformat(), proposal["id"]))
    assert not db.proposal_seen("elapsed")
    execute("UPDATE proposals SET created_at = ? WHERE id = ?",
            ((now - timedelta(days=30) + timedelta(minutes=5)).isoformat(), proposal["id"]))
    assert db.proposal_seen("elapsed")
    event = db.record_swipe("snooze", card)
    assert "snooze" not in db.SWIPE_LABEL_EVENTS
    assert db.get_topic_weight("Python") == 1.0
    assert db.get_item_by_id(card)["is_read"] == 0
    assert not db.get_swipe_deck()
    execute("UPDATE behavior_events SET created_at = ? WHERE id = ?",
            ((now - timedelta(hours=24, minutes=5)).isoformat(), event["id"]))
    assert [row["id"] for row in db.get_swipe_deck()] == [card]


def test_swipe_is_atomic_idempotent_and_shared_with_api():
    card = item(tech_tags=["Python", "Python"])
    with TestClient(app, headers=headers()) as client:
        first = client.post("/api/behavior/event", json={"event_type": "swipe_star", "item_id": card})
        assert first.json()["duplicate"] is False
        weight = db.get_topic_weight("Python")
        assert db.record_swipe("swipe_down", card, source="telegram")["duplicate"] is True
        assert db.get_topic_weight("Python") == weight
        assert len(execute("SELECT * FROM behavior_events WHERE item_id = ?", (card,))) == 1
        saved = db.get_item_by_id(card)
        assert saved["is_read"] == saved["is_starred"] == 1
        db.update_item_field(card, {"is_read": 0})
        assert not db.get_swipe_deck()
        assert client.post("/api/behavior/event", json={
            "event_type": "view", "item_id": "missing"}).status_code == 404


def test_proposal_card_dedup_is_atomic_under_concurrent_writers():
    def save(index):
        return db.save_proposal({"dedup_key": "concurrent"}, item_data={
            "url": f"proposal://synthetic/{index}", "title_l1": "test", "origin": "proposal"})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert sum(result is not None for result in results) == 1
    assert len(execute("SELECT * FROM items WHERE origin = 'proposal'")) == 1
    with pytest.raises(ValueError):
        db.save_proposal({"dedup_key": "rollback", "impact": "invalid"}, item_data={
            "url": "proposal://synthetic/rollback", "title_l1": "rollback"})
    assert not execute("SELECT * FROM items WHERE url = 'proposal://synthetic/rollback'")


def test_reference_validation_cleanup_and_init_idempotency(isolated_runtime):
    target = db.add_watch_target("test", str(isolated_runtime))
    card = item()
    db.update_watch_target(target["id"], {"fingerprint_item_id": card, "fingerprint_version": "test"})
    proposal = db.save_proposal({"item_id": card, "target_id": target["id"]})
    db.log_behavior_event("proposal_approve", card, proposal["id"])
    with pytest.raises(ValueError):
        db.save_proposal({"item_id": card, "target_id": "missing"})
    with pytest.raises(ValueError):
        db.update_watch_target(target["id"], {"fingerprint_item_id": "missing"})
    with pytest.raises(ValueError):
        db.update_item_field(card, {"title_l1 = 'injected' --": "bad"})
    for _ in range(3):
        db.init_db()
    assert len(execute("SELECT * FROM items")) == 1
    assert len(execute("SELECT * FROM items_fts")) == 1
    assert db.delete_item(card)
    assert not execute("SELECT * FROM proposals")
    assert not execute("SELECT * FROM behavior_events")
    assert db.get_watch_target(target["id"])["fingerprint_item_id"] is None


@pytest.mark.asyncio
async def test_summary_consent_does_not_export_docs_or_code(isolated_runtime, monkeypatch):
    root = isolated_runtime / "project"
    root.mkdir()
    (root / "README.md").write_text("PRIVATE_DOC_MARKER")
    (root / "main.py").write_text("PRIVATE_CODE_MARKER")
    target = db.add_watch_target("synthetic", str(root), read_scope={
        "filenames": True, "readme": True, "code": True}, outbound_consent={"summary": True})
    provider = Mock(generate_json=AsyncMock(return_value={"title_l1": "fingerprint", "tech_tags": ["Python"]}))
    monkeypatch.setattr(scanner, "get_primary_provider", lambda: provider)
    result = await scanner.scan_target(target)
    assert result["fingerprint_updated"]
    prompt = provider.generate_json.call_args.args[0]
    assert "PRIVATE_DOC_MARKER" not in prompt and "PRIVATE_CODE_MARKER" not in prompt
    assert "檔案數" in prompt
    assert not (await scanner.scan_target(target))["changed"]
    (root / "main.py").write_text("PRIVATE_CODE_MARKER_NEW")
    assert (await scanner.scan_target(target))["changed"]
    db.update_watch_target(target["id"], {"outbound_consent": {"docs": True}})
    await scanner.scan_target(target)
    prompt = provider.generate_json.call_args.args[0]
    assert "PRIVATE_DOC_MARKER" in prompt and "PRIVATE_CODE_MARKER" not in prompt


@pytest.mark.asyncio
async def test_concurrent_risk_scan_deduplicates_before_provider(isolated_runtime, monkeypatch):
    (isolated_runtime / "password.txt").write_text("SYNTHETIC_NEVER_READ")
    target = db.add_watch_target("risk", str(isolated_runtime), preset="strict")
    provider = Mock(generate_json=AsyncMock(return_value={"title_l1": "fingerprint"}))
    monkeypatch.setattr(scanner, "get_primary_provider", lambda: provider)
    await asyncio.gather(scanner.scan_target(target), scanner.scan_target(target))
    assert provider.generate_json.await_count == 1
    assert len(db.get_proposals()) == 1


@pytest.mark.asyncio
async def test_relevance_never_exports_historical_fingerprint_and_dedups_llm(isolated_runtime, monkeypatch):
    target = db.add_watch_target("project", str(isolated_runtime), preset="strict")
    fingerprint = item("fingerprint", tech_tags=["Python", "SQLite"], summary_l1="PRIVATE_HISTORY_MARKER")
    db.update_watch_target(target["id"], {"fingerprint_item_id": fingerprint, "fingerprint_version": "test"})
    public = db.get_item_by_id(item("public", tech_tags=["Python", "SQLite"]))
    provider = Mock(generate_json=AsyncMock(return_value={"relevant": True}))
    monkeypatch.setattr(relevance, "get_primary_provider", lambda: provider)
    results = await asyncio.gather(relevance.maybe_propose_for_item(public), relevance.maybe_propose_for_item(public))
    assert sum(result is not None for result in results) == 1
    assert provider.generate_json.await_count == 1
    assert "PRIVATE_HISTORY_MARKER" not in provider.generate_json.call_args.args[0]


@pytest.mark.asyncio
async def test_worker_claim_failure_cooldown_and_exclusive_ownership(monkeypatch):
    import app.queue.worker as module
    claim = Mock(side_effect=[RuntimeError("synthetic claim failure"), None])
    monkeypatch.setattr(module, "claim_next_task", claim)
    worker = TaskWorker(concurrency=2, poll_interval=0.005)
    worker._rate_limit_until = time.monotonic() + 0.01
    worker.start()
    try:
        other = TaskWorker()
        with pytest.raises(RuntimeError, match="owns"):
            other.start()
        assert db.reset_stale_tasks() == 0
        await asyncio.sleep(0.035)
    finally:
        await worker.stop()
    assert worker.semaphore._value == 2
    assert claim.call_count >= 2
    recovered = TaskWorker(poll_interval=1)
    recovered.start()
    await recovered.stop()


@pytest.mark.asyncio
async def test_followup_queue_is_bounded_and_shutdown_cancels_work(monkeypatch):
    monkeypatch.setattr(settings, "RELEVANCE_CONCURRENCY", 1)
    monkeypatch.setattr(settings, "RELEVANCE_QUEUE_SIZE", 1)
    pool = FollowUpPool()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def work():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    pool.start()
    assert pool.submit(work)
    await entered.wait()
    assert pool.submit(work)
    assert not pool.submit(work)
    await pool.stop(timeout=0.01)
    assert cancelled.is_set() and not pool._workers
    assert not pool.submit(work)


def test_backup_online_wal_snapshot_and_parallel_lock(isolated_runtime, monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_SINK", "local")
    card = item()
    held = db.get_db_connection()
    try:
        held.execute("PRAGMA journal_mode=WAL")
        held.execute("UPDATE items SET summary_l1 = 'wal snapshot' WHERE id = ?", (card,))
        held.commit()
        result = backup.run_backup()
        assert result["status"] == "ok"
        restore = isolated_runtime / "restored"
        with zipfile.ZipFile(result["file_path"]) as archive:
            archive.extract("omnikeep.db", restore)
        with closing(sqlite3.connect(restore / "omnikeep.db")) as conn:
            assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
            assert conn.execute("SELECT summary_l1 FROM items WHERE id = ?", (card,)).fetchone()[0] == "wal snapshot"
            assert conn.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0] == 1
        ownership = FileLock(isolated_runtime / "backups/.backup.lock")
        assert ownership.acquire()
        try:
            assert backup.run_backup()["status"] == "busy"
        finally:
            ownership.release()
    finally:
        held.close()


@pytest.mark.asyncio
async def test_backup_cancel_waits_for_io_thread(monkeypatch):
    entered, finish, completed = threading.Event(), threading.Event(), threading.Event()

    def slow_backup():
        entered.set()
        finish.wait(timeout=2)
        completed.set()
        return {"status": "ok"}

    monkeypatch.setattr(backup, "run_backup", slow_backup)
    task = asyncio.create_task(backup.run_backup_async())
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed.is_set()


@pytest.mark.asyncio
async def test_backup_scheduler_recovers_from_initial_query_failure(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_SINK", "local")
    monkeypatch.setattr(settings, "BACKUP_HOUR", 0)
    monkeypatch.setattr(backup, "last_successful_date", Mock(side_effect=[RuntimeError("transient"), None]))
    run = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(backup, "run_backup_async", run)
    monkeypatch.setattr(backup.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()]))
    with pytest.raises(asyncio.CancelledError):
        await backup.backup_loop(interval_seconds=1)
    run.assert_awaited_once()


@pytest.mark.asyncio
async def test_lifespan_closes_consumers_and_http_even_when_stop_fails(monkeypatch):
    import app.main as main
    from app.background import follow_up_pool
    import app.bot.telegram_bot as telegram

    events = []

    async def poll():
        try:
            await asyncio.Event().wait()
        finally:
            events.append("poll_stopped")

    async def stop_radar():
        events.append("radar_stopped")
        raise RuntimeError("synthetic stop failure")

    async def record(event):
        events.append(event)

    bot = Mock(run_polling=poll)
    bot.close = lambda: record("bot_closed")
    monkeypatch.setattr(settings, "BACKGROUND_SERVICES_ENABLED", True)
    monkeypatch.setattr(settings, "RADAR_ENABLED", True)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "synthetic-token")
    monkeypatch.setattr(main.task_worker, "start", Mock())
    monkeypatch.setattr(main.task_worker, "stop", lambda: record("worker_stopped"))
    monkeypatch.setattr(main.radar_scheduler, "start", Mock())
    monkeypatch.setattr(main.radar_scheduler, "stop", stop_radar)
    monkeypatch.setattr(follow_up_pool, "start", Mock())
    monkeypatch.setattr(follow_up_pool, "stop", lambda: record("pool_stopped"))
    monkeypatch.setattr(telegram, "get_telegram_bot", lambda: bot)
    with pytest.raises(RuntimeError, match="synthetic stop failure"):
        async with main.lifespan(main.app):
            await asyncio.sleep(0)
    assert events == ["poll_stopped", "radar_stopped", "worker_stopped", "pool_stopped", "bot_closed"]


@pytest.mark.asyncio
async def test_lifespan_drains_pool_after_startup_failure(monkeypatch):
    import app.main as main
    from app.background import follow_up_pool

    monkeypatch.setattr(settings, "BACKGROUND_SERVICES_ENABLED", True)
    monkeypatch.setattr(follow_up_pool, "start", Mock())
    stop = AsyncMock()
    monkeypatch.setattr(follow_up_pool, "stop", stop)
    monkeypatch.setattr(main.task_worker, "start", Mock(side_effect=RuntimeError("startup failure")))
    with pytest.raises(RuntimeError, match="startup failure"):
        async with main.lifespan(main.app):
            pytest.fail("Startup should fail before yielding")
    stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_preserves_concurrency_after_claim_failure(monkeypatch):
    import app.queue.worker as module

    claims = iter([RuntimeError("claim failure"), *({"id": str(n)} for n in range(6))])

    def claim():
        value = next(claims, None)
        if isinstance(value, Exception):
            raise value
        return value

    worker = TaskWorker(concurrency=2, poll_interval=0.001)
    active = peak = completed = 0
    done = asyncio.Event()

    async def process(task):
        nonlocal active, peak, completed
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(0.01)
            completed += 1
            if completed == 6:
                done.set()
        finally:
            active -= 1

    monkeypatch.setattr(module, "claim_next_task", claim)
    monkeypatch.setattr(worker, "_process_task", process)
    worker.start()
    try:
        await asyncio.wait_for(done.wait(), timeout=2)
    finally:
        await worker.stop()
    assert peak == 2 and completed == 6 and worker.semaphore._value == 2


@pytest.mark.asyncio
async def test_backup_scheduler_retries_failed_result(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_SINK", "local")
    monkeypatch.setattr(settings, "BACKUP_HOUR", 0)
    monkeypatch.setattr(backup, "last_successful_date", lambda: None)
    run = AsyncMock(side_effect=[{"status": "failed"}, {"status": "ok"}])
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    monkeypatch.setattr(backup, "run_backup_async", run)
    monkeypatch.setattr(backup.asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await backup.backup_loop(interval_seconds=1)
    assert run.await_count == 2
    assert [call.args[0] for call in sleep.await_args_list] == [600, 1]


def test_backup_git_only_stages_and_commits_current_archive(isolated_runtime, monkeypatch):
    repo = isolated_runtime / "repo"
    (repo / ".git").mkdir(parents=True)
    archive = isolated_runtime / "omnikeep-backup-fixture.zip"
    archive.write_bytes(b"synthetic archive")
    monkeypatch.setattr(settings, "BACKUP_GIT_REPO_DIR", str(repo))
    run = Mock(return_value=Mock(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(backup.subprocess, "run", run)
    backup._git_push(archive)
    commands = [call.args[0] for call in run.call_args_list]
    assert commands[0][3:] == ["add", "--", archive.name]
    assert commands[1][3:5] == ["commit", "--only"]
    assert commands[1][-2:] == ["--", archive.name]
    assert commands[2][3:] == ["push"]


def test_failed_remote_backup_preserves_local_history(isolated_runtime, monkeypatch):
    root = isolated_runtime / "backups"
    root.mkdir()
    old = root / "omnikeep-backup-20000101-000000.zip"
    old.write_bytes(b"old snapshot")
    monkeypatch.setattr(settings, "BACKUP_SINK", "rclone")
    monkeypatch.setattr(settings, "BACKUP_KEEP", 1)
    monkeypatch.setattr(backup, "_rclone_push", Mock(side_effect=RuntimeError("remote unavailable")))
    result = backup.run_backup()
    assert result["status"] == "failed"
    assert old.exists() and len(list(root.glob("*.zip"))) == 2


@pytest.mark.asyncio
async def test_youtube_radar_rejects_private_entry_and_redirect(monkeypatch):
    from app.radar.adapters.youtube import YouTubeAdapter

    adapter = YouTubeAdapter()
    with pytest.raises(network.UnsafeURL):
        await adapter._resolve_channel_rss_url("http://127.0.0.1/channel/UCfixture")
    contacted = []

    async def respond(request):
        contacted.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://169.254.169.254/private"})

    monkeypatch.setattr(network, "PublicHTTPTransport", lambda: httpx.MockTransport(respond))
    result = await adapter.fetch_latest({"id": "synthetic", "url": "https://public.invalid/@fixture"})
    assert result == [] and contacted
    assert all(url == "https://public.invalid/@fixture" for url in contacted)


def test_media_rejects_external_downloader_protocols():
    from app.parsers.media_network import PublicYoutubeDL

    with PublicYoutubeDL({"quiet": True, "no_warnings": True}) as downloader:
        assert downloader.params["external_downloader_args"]["ffmpeg_i"] == [
            "-protocol_whitelist", "file,pipe"]
        for protocol in ("rtmp", "rtmpe", "websocket_frag"):
            with pytest.raises(network.UnsafeURL):
                downloader.dl("unused.mp4", {"url": "https://media.invalid/video", "protocol": protocol})


def test_all_ffmpeg_inputs_disable_nested_network(isolated_runtime, monkeypatch):
    from app.parsers import reel

    audio = isolated_runtime / "audio.mp3"
    audio.write_bytes(b"synthetic media" * 50)
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return Mock(returncode=0, stdout=b"")

    monkeypatch.setattr(reel.subprocess, "run", run)
    monkeypatch.setattr(reel, "get_local_whisper_model", lambda: Mock())
    reel.transcribe_local_whisper(str(audio))
    reel.extract_scene_tile(str(audio), str(isolated_runtime / "tile.jpg"))
    reel.extract_audio_stream(str(audio), str(isolated_runtime / "output.mp3"))
    assert len(commands) == 4
    for command in commands:
        index = command.index("-protocol_whitelist")
        assert index < command.index("-i") and command[index + 1] == "file,pipe"


@pytest.mark.asyncio
async def test_media_cancellation_joins_native_io_before_cleanup():
    from app.parsers.reel import _run_thread

    entered, finish, completed = threading.Event(), threading.Event(), threading.Event()

    def work():
        entered.set()
        finish.wait(timeout=2)
        completed.set()

    task = asyncio.create_task(_run_thread(work))
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0.01)
    assert not task.done()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed.is_set()
