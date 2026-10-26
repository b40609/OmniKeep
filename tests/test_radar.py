from app.config import settings
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import Response
from app.radar.adapters.github import GitHubAdapter
from app.radar.adapters.rss import RSSAdapter
from app.radar.recommender import score_item, rank_items_with_exploration
from app.radar.scheduler import is_source_due, run_radar_cycle, RadarScheduler
from app.database import tune_topic_signal, save_item, get_item_by_id, delete_item

# ── 1. GitHub Adapter Tests ──────────────────────────────────

@pytest.mark.asyncio
async def test_github_adapter_releases():
    adapter = GitHubAdapter()
    source = {
        "id": "src_gh_repo_test",
        "name": "FastAPI",
        "source_type": "github",
        "url": "https://github.com/tiangolo/fastapi",
        "tier": 1,
        "last_published_at": "2026-01-01T00:00:00Z"
    }

    mock_releases = [
        {
            "tag_name": "0.115.0",
            "name": "Release 0.115.0",
            "published_at": "2026-02-01T12:00:00Z",
            "html_url": "https://github.com/tiangolo/fastapi/releases/tag/0.115.0",
            "body": "Fixes and improvements."
        },
        {
            "tag_name": "0.114.0",
            "name": "Release 0.114.0",
            "published_at": "2025-12-01T12:00:00Z",
            "html_url": "https://github.com/tiangolo/fastapi/releases/tag/0.114.0",
            "body": "Older release."
        }
    ]

    mock_resp = Response(
        status_code=200,
        json=mock_releases,
        headers={"etag": '"etag-fastapi-123"'}
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        items = await adapter.fetch_latest(source)

        assert len(items) == 1  # Only the newer one after 2026-01-01
        assert items[0].url == "https://github.com/tiangolo/fastapi/releases/tag/0.115.0"
        assert items[0].author == "tiangolo"
        assert items[0].tier == 1
        assert "0.115.0" in items[0].title

@pytest.mark.asyncio
async def test_github_adapter_search():
    adapter = GitHubAdapter()
    source = {
        "id": "src_gh_search_test",
        "name": "Agent Frameworks",
        "source_type": "github",
        "url": "https://github.com/search?q=topic%3Aagent&s=stars&o=desc",
        "tier": 2
    }

    mock_search_payload = {
        "total_count": 1,
        "items": [
            {
                "full_name": "agno-agi/agno",
                "html_url": "https://github.com/agno-agi/agno",
                "description": "Multi-modal Agent Framework",
                "stargazers_count": 12500,
                "forks_count": 1500,
                "pushed_at": "2026-10-20T10:00:00Z"
            }
        ]
    }

    mock_resp = Response(
        status_code=200,
        json=mock_search_payload,
        headers={"etag": '"etag-search-456"'}
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        items = await adapter.fetch_latest(source)

        assert len(items) == 1
        assert items[0].url == "https://github.com/agno-agi/agno"
        assert "agno-agi/agno" in items[0].title
        assert "12500" in items[0].title or "12500" in items[0].content
        assert items[0].author == "agno-agi"
        assert items[0].source_type == "github"

@pytest.mark.asyncio
async def test_github_adapter_trending():
    adapter = GitHubAdapter()
    source = {
        "id": "src_gh_trending_test",
        "name": "GitHub Trending",
        "source_type": "github",
        "url": "https://github.com/trending",
        "tier": 2
    }

    mock_html = """
    <html>
      <body>
        <article class="Box-row">
          <h2 class="h3 lh-condensed">
            <a href="/owner1/repo-alpha">owner1 / repo-alpha</a>
          </h2>
        </article>
        <article class="Box-row">
          <h2 class="h3 lh-condensed">
            <a href="/owner2/repo-beta">owner2 / repo-beta</a>
          </h2>
        </article>
      </body>
    </html>
    """

    mock_resp = Response(status_code=200, text=mock_html)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        items = await adapter.fetch_latest(source)

        assert len(items) == 2
        assert items[0].url == "https://github.com/owner1/repo-alpha"
        assert items[1].url == "https://github.com/owner2/repo-beta"
        assert items[0].author == "owner1"
        assert items[1].author == "owner2"

# ── 2. RSS Adapter Tests ────────────────────────────────────

@pytest.mark.asyncio
async def test_rss_adapter_fetch_and_hot_hours():
    adapter = RSSAdapter()
    source = {
        "id": "src_rss_test",
        "name": "Tech Blog",
        "source_type": "rss",
        "url": "https://example.com/rss.xml",
        "tier": 2
    }

    sample_rss_xml = """<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
      <channel>
        <title>Tech Blog</title>
        <link>https://example.com</link>
        <description>Sample Blog</description>
        <item>
          <title>Deep Dive into Rust Async</title>
          <link>https://example.com/rust-async</link>
          <description>Understanding async runtimes</description>
          <pubDate>Wed, 22 Oct 2026 14:00:00 +0000</pubDate>
        </item>
        <item>
          <title>SQLite WAL Internals</title>
          <link>https://example.com/sqlite-wal</link>
          <description>How write-ahead logs work</description>
          <pubDate>Thu, 23 Oct 2026 14:30:00 +0000</pubDate>
        </item>
      </channel>
    </rss>
    """

    mock_resp = Response(
        status_code=200,
        text=sample_rss_xml,
        headers={"etag": '"rss-etag-789"'}
    )

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        items = await adapter.fetch_latest(source)

        assert len(items) == 2
        assert items[0].url == "https://example.com/rust-async"
        assert "Deep Dive into Rust Async" in items[0].title
        assert items[1].url == "https://example.com/sqlite-wal"

    # Test hot_hours calculation
    # 4 samples: three at 14:00, one at 08:00
    dates = [
        datetime(2026, 10, 20, 14, 0),
        datetime(2026, 10, 21, 14, 0),
        datetime(2026, 10, 22, 14, 0),
        datetime(2026, 10, 23, 8, 0),
    ]
    hot = adapter.calculate_hot_hours(dates)
    assert 14 in hot
    assert len(hot) >= 1

# ── 3. 80/20 Algorithm & Recommender Tests ───────────────────

def test_score_item_and_muted_shield():
    # Setup topic signals
    tune_topic_signal("FastAPI", "boost")  # Boost FastAPI
    tune_topic_signal("SpamCrypto", "mute")  # Shield / Mute SpamCrypto

    # Normal score with boosted tag
    score, is_blocked = score_item(["FastAPI", "Python"], tier=1)
    assert not is_blocked
    assert score > 1.25  # Boosted + Tier 1 multiplier (1.25)

    # Muted tag hard block
    score_muted, is_blocked_muted = score_item(["SpamCrypto", "AI"], tier=1)
    assert is_blocked_muted
    assert score_muted <= -100.0

def test_rank_items_with_exploration():
    tune_topic_signal("SpamCrypto", "mute")
    items = [
        {"id": f"item_{i}", "tech_tags": ["FastAPI"], "tier": 1, "title": f"Item {i}"}
        for i in range(10)
    ]
    # Add a muted item
    items.append({"id": "item_bad", "tech_tags": ["SpamCrypto"], "tier": 1, "title": "Bad"})

    ranked = rank_items_with_exploration(items, exploration_ratio=0.2)
    # The bad item must be stripped
    ranked_ids = [it["id"] for it in ranked]
    assert "item_bad" not in ranked_ids
    assert len(ranked) == 10

    # Check that exploration interleaving exists when rest_pool is populated
    has_explore = any(it.get("is_exploration") for it in ranked)
    assert has_explore

# ── 4. Scheduler Lifecycle & Source Due Tests ─────────────────

def test_is_source_due_logic():
    now = datetime.now(timezone.utc)
    
    # 1. Never fetched before -> Due
    src_new = {"id": "src_1", "last_fetched_at": None, "check_interval_minutes": 60}
    assert is_source_due(src_new)

    # 2. Fetched 10 minutes ago, interval 60 -> Not due
    src_recent = {
        "id": "src_2",
        "last_fetched_at": (now - timedelta(minutes=10)).isoformat(),
        "check_interval_minutes": 60,
        "hot_hours": []
    }
    assert not is_source_due(src_recent)

    # 3. Fetched 70 minutes ago, interval 60 -> Due
    src_overdue = {
        "id": "src_3",
        "last_fetched_at": (now - timedelta(minutes=70)).isoformat(),
        "check_interval_minutes": 60,
        "hot_hours": []
    }
    assert is_source_due(src_overdue)

    # 4. Force mode -> Always due
    assert is_source_due(src_recent, force=True)

@pytest.mark.asyncio
async def test_scheduler_lifecycle():
    scheduler = RadarScheduler()
    assert not scheduler.is_running

    # Start with a fast initial delay to test background task creation
    scheduler.start(initial_delay=999.0)
    assert scheduler.is_running
    assert scheduler._task is not None

    # Stop scheduler gracefully
    await scheduler.stop()
    assert not scheduler.is_running
    assert scheduler._task.done()

# ── 5. FastAPI Endpoints & Lifespan Integration Tests ─────────

@pytest.mark.asyncio
async def test_radar_api_endpoints():
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        # 1. Create a GitHub search source
        res_create = await client.post("/api/radar/sources", json={
            "name": "Local Agent Search",
            "source_type": "github",
            "url": "https://github.com/search?q=topic%3Aagent&s=updated",
            "tier": 2,
            "check_interval_minutes": 30
        })
        assert res_create.status_code == 200
        source_id = res_create.json()["source_id"]

        # 2. List sources
        res_list = await client.get("/api/radar/sources")
        assert res_list.status_code == 200
        sources = res_list.json()["sources"]
        assert any(s["id"] == source_id for s in sources)

        # 3. Trigger scan in background
        with patch("app.routers.radar.run_radar_cycle", new_callable=AsyncMock) as mock_cycle:
            mock_cycle.return_value = {"sources_scanned": 1, "new_items_count": 0, "new_items": [], "ranked_items": []}
            res_scan = await client.post("/api/radar/scan?async_mode=false&force=true")
            assert res_scan.status_code == 200
            assert res_scan.json()["status"] == "completed"

        # 4. Clean up source
        res_del = await client.delete(f"/api/radar/sources/{source_id}")
        assert res_del.status_code == 200

@pytest.mark.asyncio
async def test_main_lifespan_integration(monkeypatch):
    monkeypatch.setattr(settings, "BACKGROUND_SERVICES_ENABLED", True)
    from app.main import app
    from app.radar.scheduler import radar_scheduler
    from contextlib import asynccontextmanager

    # Test that entering and exiting the lifespan manages radar_scheduler cleanly
    async with app.router.lifespan_context(app):
        assert radar_scheduler.is_running

    assert not radar_scheduler.is_running

@pytest.mark.asyncio
async def test_radar_network_outage_resilience():
    import httpx
    # Simulate complete network disconnection
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.ConnectError("Network is completely unreachable")
        res = await run_radar_cycle(force=True, auto_digest=False)
        assert isinstance(res, dict)
        assert res["new_items_count"] == 0
        assert res["ranked_items"] == []


