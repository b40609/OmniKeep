"""Vector search reports the real cosine similarity, the same on the sqlite-vec path and the
numpy fallback. vec_items measures L2, and 1 - L2 used to be passed off as the similarity."""
import math
import os

import pytest

from app import vector
from app.vector import init_vector_db, is_sqlite_vec_available, search_similar_items, store_item_embedding

DIM = 256
QUERY = [1.0] + [0.0] * (DIM - 1)


def _at(cosine, scale=1.0):
    """A vector whose cosine with QUERY is `cosine`, of length `scale`."""
    return [scale * cosine, scale * math.sqrt(1.0 - cosine * cosine)] + [0.0] * (DIM - 2)


# name -> (vector, true cosine with QUERY)
VECTORS = {
    "same": (_at(1.0), 1.0),
    "cos08": (_at(0.8), 0.8),
    "cos05": (_at(0.5), 0.5),
    "cos02": (_at(0.2), 0.2),
    "long08": (_at(0.8, scale=3.0), 0.8),   # not unit length: as a remote endpoint may return
    "short06": (_at(0.6, scale=0.25), 0.6),
    "opposite": (_at(-0.5), -0.5),
    "zero": ([0.0] * DIM, 0.0),
}


def _require_sqlite_vec():
    if is_sqlite_vec_available():
        return
    if os.environ.get("CI"):
        pytest.fail("sqlite-vec cannot load in CI; the vector path would otherwise go untested")
    pytest.skip("sqlite-vec cannot load into this Python's sqlite3")


@pytest.fixture
def stored():
    init_vector_db()
    for name, (vec, _cosine) in VECTORS.items():
        store_item_embedding(name, vec, model="m")


def _numpy_only(monkeypatch):
    monkeypatch.setattr(vector, "load_vec_extension", lambda conn: False)


def test_sqlite_vec_path_returns_the_true_cosine(stored, monkeypatch):
    _require_sqlite_vec()
    monkeypatch.setattr(vector, "cosine_similarity",
                        lambda *a: pytest.fail("the numpy fallback ran instead of sqlite-vec"))
    results = search_similar_items(QUERY, limit=20, min_similarity=-1.0)
    found = {r["item_id"]: r for r in results}
    assert set(found) == set(VECTORS)
    for name, (_vec, cosine) in VECTORS.items():
        assert found[name]["similarity"] == pytest.approx(cosine, abs=1e-3), name
        assert found[name]["distance"] == pytest.approx(1.0 - cosine, abs=1e-3), name
    # Best first by cosine, although the L2 order puts the long vector last.
    assert [r["similarity"] for r in results] == sorted((r["similarity"] for r in results), reverse=True)
    assert {r["item_id"] for r in results[:3]} == {"same", "cos08", "long08"}


def test_the_threshold_means_cosine(stored):
    _require_sqlite_vec()
    # 0.35 is the related-items threshold. Read as 1 - L2, cosine 0.8 scored 0.37 and 0.5 scored 0.
    assert {r["item_id"] for r in search_similar_items(QUERY, limit=20, min_similarity=0.35)} == \
        {"same", "cos08", "long08", "short06", "cos05"}
    assert {r["item_id"] for r in search_similar_items(QUERY, limit=20, min_similarity=0.1)} == \
        {"same", "cos08", "long08", "short06", "cos05", "cos02"}


def test_both_paths_agree(stored, monkeypatch):
    _require_sqlite_vec()
    for threshold in (-1.0, 0.1, 0.35):
        with_vec = search_similar_items(QUERY, limit=20, min_similarity=threshold)
        with monkeypatch.context() as patched:
            _numpy_only(patched)
            with_numpy = search_similar_items(QUERY, limit=20, min_similarity=threshold)
        assert {r["item_id"] for r in with_vec} == {r["item_id"] for r in with_numpy}
        by_id = {r["item_id"]: r for r in with_numpy}
        for r in with_vec:
            assert r["similarity"] == pytest.approx(by_id[r["item_id"]]["similarity"], abs=1e-3)
            assert r["distance"] == pytest.approx(by_id[r["item_id"]]["distance"], abs=1e-3)


def test_numpy_fallback_returns_the_true_cosine(stored, monkeypatch):
    _numpy_only(monkeypatch)
    found = {r["item_id"]: r["similarity"] for r in search_similar_items(QUERY, limit=20, min_similarity=-1.0)}
    for name, (_vec, cosine) in VECTORS.items():
        assert found[name] == pytest.approx(cosine, abs=1e-3), name


def test_model_filter_keeps_the_true_cosine(stored):
    _require_sqlite_vec()
    store_item_embedding("other-model", _at(0.9), model="another")
    found = {r["item_id"]: r["similarity"] for r in search_similar_items(QUERY, limit=3, min_similarity=0.1, model="m")}
    assert "other-model" not in found
    assert found["cos08"] == pytest.approx(0.8, abs=1e-3) and found["long08"] == pytest.approx(0.8, abs=1e-3)
