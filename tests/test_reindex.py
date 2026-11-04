"""The vector index audit finds local vectors labelled as a remote model, and the rebuild
command repairs or re-embeds them only when told to, after taking a restorable backup."""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import numpy as np
import pytest

from app import network, reindex
from app.backup import inspect_backup
from app.config import settings
from app.database import create_rule, delete_rule, get_item_by_id, save_item
from app.vector import (
    LOCAL_EMBEDDING_MODEL,
    get_item_embedding,
    init_vector_db,
    item_embedding_text,
    local_embedding,
    search_similar_items,
    store_item_embedding,
)
from scripts.rebuild_embeddings import main as rebuild

REMOTE = "text-embedding-3-small"


def _item(title, **extra):
    return save_item({"url": f"https://example.com/{title}", "title_l1": title, "summary_l1": f"{title} 摘要",
                      "tech_tags": ["SQLite", title], **extra})


def _local(item_id):
    return local_embedding(item_embedding_text(get_item_by_id(item_id)), 256)


@pytest.fixture
def index(monkeypatch):
    """An index as older versions left it, plus the other cases the audit must tell apart."""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", REMOTE)
    init_vector_db()
    ids = {name: _item(name) for name in ("mislabeled", "remote", "local", "short", "unindexed")}
    ids["stub"] = _item("stub", analysis_status="pending")
    store_item_embedding(ids["mislabeled"], _local(ids["mislabeled"]), model=REMOTE)  # the old bug
    rng = np.random.default_rng(7)
    remote = rng.normal(size=256)
    store_item_embedding(ids["remote"], (remote / np.linalg.norm(remote)).tolist(), model=REMOTE)
    store_item_embedding(ids["local"], _local(ids["local"]), model=LOCAL_EMBEDDING_MODEL)
    store_item_embedding(ids["short"], [0.1] * 128, model=LOCAL_EMBEDDING_MODEL)  # another dim
    store_item_embedding("deleted-item", [0.1] * 256, model=REMOTE)
    return ids


def test_audit_without_an_api_key_targets_local_vectors(index):
    report = reindex.audit_embeddings()
    assert report["target_model"] == LOCAL_EMBEDDING_MODEL
    assert report["mislabeled_local"] == [index["mislabeled"]]
    assert sorted(report["stale"]) == sorted([index["remote"], index["short"]])
    assert report["dim_mismatch"] == [index["short"]]
    assert report["missing"] == [index["unindexed"]]  # the pending radar stub is not counted
    assert report["orphans"] == ["deleted-item"]
    assert report["labels"] == {REMOTE: 3, LOCAL_EMBEDDING_MODEL: 2}
    assert report["actual"] == {LOCAL_EMBEDDING_MODEL: 2, REMOTE: 1}


def test_audit_with_an_api_key_flags_every_local_vector(index, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "synthetic-key")
    report = reindex.audit_embeddings()
    assert report["target_model"] == REMOTE
    assert sorted(report["stale"]) == sorted([index["mislabeled"], index["local"], index["short"]])


def test_dry_run_changes_nothing(index, capsys):
    before = get_item_embedding(index["mislabeled"])
    assert rebuild(["--repair", "--reembed"]) == 0
    out = capsys.readouterr().out
    assert "Dry run: nothing changed" in out
    assert reindex.audit_embeddings()["mislabeled_local"] == [index["mislabeled"]]
    assert get_item_embedding(index["mislabeled"]) == before
    assert not list(Path(settings.BACKUP_DIR).glob("omnikeep-prerebuild-*.zip"))


def test_repair_relabels_without_api_calls_after_a_backup(index, capsys, monkeypatch):
    calls = AsyncMock()
    monkeypatch.setattr(reindex, "generate_embedding_with_model", calls)
    before = get_item_embedding(index["mislabeled"])

    assert rebuild(["--repair", "--yes"]) == 0

    calls.assert_not_awaited()
    report = reindex.audit_embeddings()
    assert report["mislabeled_local"] == [] and report["labels"][LOCAL_EMBEDDING_MODEL] == 3
    assert get_item_embedding(index["mislabeled"]) == before  # same vector, true label
    archives = list(Path(settings.BACKUP_DIR).glob("omnikeep-prerebuild-*.zip"))
    assert len(archives) == 1 and inspect_backup(archives[0])["format"] == 2  # restorable
    assert "Relabelled 1 rows" in capsys.readouterr().out


def _embeddings_api(monkeypatch, status=200):
    """An OpenAI-compatible endpoint: a deterministic 'remote' vector per input."""
    seen = []

    def handler(request):
        text = request.read().decode()
        seen.append(text)
        if status != 200:
            return httpx.Response(status, text="unavailable")
        vec = np.random.default_rng(abs(hash(text)) % 2**32).normal(size=256)
        return httpx.Response(200, json={"data": [{"embedding": (vec / np.linalg.norm(vec)).tolist()}]})

    monkeypatch.setattr(network, "public_http_client",
                        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


def test_reembed_moves_stale_rows_into_the_query_models_space(index, monkeypatch, capsys):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "synthetic-key")
    seen = _embeddings_api(monkeypatch)

    assert rebuild(["--reembed", "--include-missing", "--yes"]) == 0

    assert len(seen) == 4  # mislabeled, local, short, unindexed: nothing else is paid for
    report = reindex.audit_embeddings()
    assert report["stale"] == [] and report["missing"] == []
    assert report["labels"][REMOTE] == 6  # 4 re-embedded + the real remote one + the orphan
    # The sqlite-vec mirror follows: the new vector finds its item first.
    new = get_item_embedding(index["mislabeled"])
    assert search_similar_items(new, limit=1)[0]["item_id"] == index["mislabeled"]


def test_reembed_stops_and_keeps_rows_when_the_endpoint_is_down(index, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "synthetic-key")
    seen = _embeddings_api(monkeypatch, status=500)
    before = {name: get_item_embedding(item_id) for name, item_id in index.items()}

    assert rebuild(["--reembed", "--yes"]) == 1

    assert len(seen) == reindex.MAX_FALLBACKS_IN_A_ROW
    assert {name: get_item_embedding(item_id) for name, item_id in index.items()} == before


def test_pipeline_indexes_the_item_as_stored_after_rules(monkeypatch):
    """New vectors are made from the same text the audit recomputes, so it can recognise them."""
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    init_vector_db()
    rule = create_rule(name="tag docs", field="url", operator="contains", value="docs.example.com",
                       action_type="add_tag", action_value="規則標籤")
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value={"title_l1": "文件", "summary_l1": "摘要", "tech_tags": ["Docs"]})
    page = {"title": "Docs", "content_raw": "內容", "cover_image": "", "author": "", "raw_html": ""}
    try:
        from app import pipeline
        with patch.object(pipeline, "get_primary_provider", return_value=provider), \
             patch.object(pipeline, "parse_web_page", AsyncMock(return_value=page)):
            item = asyncio.run(pipeline.run_pipeline("https://docs.example.com/guide"))
    finally:
        delete_rule(rule)
    stored = get_item_by_id(item["id"])
    assert "規則標籤" in stored["tech_tags"]
    assert np.allclose(get_item_embedding(item["id"]), _local(item["id"]), atol=1e-6)
    assert reindex.audit_embeddings()["actual"] == {LOCAL_EMBEDDING_MODEL: 1}
