"""A question finds the related items, or says that semantic search took no part.

Two faults met on a live install: the query vector fell back to the hashed stand-in
while the index was made by a real model, so the few stand-in rows in the index were
cited as if related; and a Chinese question, written without spaces, was searched as
one word that no item contains.
"""
import asyncio
import logging
from contextlib import closing

import pytest

import app.brain as brain
from app import mcp_server, reindex, vector
from app.database import (count_items, expand_search_words, get_db_connection, get_items, init_db, save_item,
                          search_candidates, search_words)
from app.vector import (LOCAL_EMBEDDING_MODEL, _deterministic_local_embedding, get_item_embedding, init_vector_db,
                        search_hybrid, store_item_embedding)

REAL_MODEL = "embeddinggemma-2"
QUESTION = "我收藏過哪些跟語音轉錄有關的內容？"


@pytest.fixture(autouse=True)
def _db():
    init_db()
    init_vector_db()
    vector._last_warned.clear()


def _item(name, title, summary="摘要", content="", day=1, **extra):
    item_id = save_item({"url": f"https://ask.test/{name}", "title_l1": title, "summary_l1": summary,
                         "content_raw": content, **extra})
    with closing(get_db_connection()) as db, db:
        db.execute("UPDATE items SET created_at = ? WHERE id = ?", (f"2026-01-{day:02d}T00:00:00+00:00", item_id))
    return item_id


def _real_vector(axis: int):
    vec = [0.0] * 256
    vec[axis] = 1.0
    return vec


def _real_model_is_configured(monkeypatch, answers: bool):
    """A real embedding model is the configured one; `answers` says whether it is up."""
    monkeypatch.setattr(vector, "target_embedding_model", lambda: REAL_MODEL)
    monkeypatch.setattr(reindex, "target_model", lambda: REAL_MODEL)

    async def embed(text, is_query=False):
        if answers:
            return _real_vector(0), REAL_MODEL
        return _deterministic_local_embedding(text), LOCAL_EMBEDDING_MODEL

    monkeypatch.setattr(vector, "generate_embedding_with_model", embed)
    monkeypatch.setattr(reindex, "generate_embedding_with_model", embed)


# ── A question typed as a sentence ──────────────────────────────

def test_a_chinese_question_is_cut_into_its_terms():
    assert expand_search_words(search_words(QUESTION)) == ["語音轉錄", "跟語", "語音", "音轉", "轉錄"]
    assert expand_search_words(["Whisper語音轉錄"]) == ["Whisper", "語音轉錄"]
    assert expand_search_words(["Whisper語音轉錄"], loose=True) == ["Whisper", "語音轉錄", "語音", "音轉", "轉錄"]
    assert expand_search_words(["語音辨識和語音合成的工具有哪些"])[:3] == ["語音辨識", "語音合成", "工具"]


def test_words_that_are_already_terms_are_left_alone():
    for query in ("fastapi", "AI agent", "語音", "語音轉錄", "Kubernetes PostgreSQL"):
        assert expand_search_words(search_words(query)) == []
    # Only a question (search_candidates) cuts a bare term into its pieces.
    assert expand_search_words(["語音轉錄"], loose=True) == ["語音轉錄", "語音", "音轉", "轉錄"]


def test_the_search_box_finds_items_for_a_whole_question():
    exact = _item("exact", "會議錄音工具", "本機語音轉錄，不上傳雲端")
    related = _item("related", "離線語音辨識引擎", "在筆電上跑的辨識模型")
    _item("other", "麵包發酵筆記", "老麵種的養法")
    found = [row["id"] for row in get_items(query=QUESTION, limit=50)]
    assert found == [exact, related]  # every term in the summary, then one term in the title
    assert count_items(query=QUESTION) == 2


def test_a_term_in_the_title_outweighs_several_in_the_raw_content():
    # A two-character piece turns up by chance in long raw content (here, a transcript header).
    _item("noise", "咖啡烘焙筆記", "淺焙與深焙", content="影片逐字稿（本機語音轉錄）今天來烘豆子", day=2)
    wanted = _item("wanted", "語音助理架構", "喚醒詞與對話管理", day=1)
    assert [row["id"] for row in get_items(query=QUESTION, limit=50)][0] == wanted


def test_an_exact_match_still_wins_and_nothing_widens():
    exact = _item("exact", "語音轉錄流程", "把錄音變成文字")
    _item("loose", "語音合成", "文字轉語音")
    assert [row["id"] for row in get_items(query="語音轉錄", limit=50)] == [exact]


def test_question_candidates_go_on_past_the_items_holding_every_word():
    every = _item("every", "Whisper ASR 語音轉錄實測", "三種模型比較")
    some = _item("some", "語音助理架構", "喚醒詞與對話管理")
    _item("other", "麵包發酵筆記", "老麵種的養法")
    query = "語音轉錄 Whisper ASR"
    assert [row["id"] for row in get_items(query=query, limit=50)] == [every]  # the search box stays strict
    assert [row["id"] for row in search_candidates(query, limit=10)] == [every, some]


# ── The vector side ─────────────────────────────────────────────

def _mostly_real_index(stand_in_text="麵包發酵筆記 老麵種的養法"):
    """Three items indexed by the real model, one that only got the hashed stand-in."""
    for n in range(3):
        store_item_embedding(_item(f"real{n}", f"向量資料庫比較 {n}"), _real_vector(n), model=REAL_MODEL)
    stand_in = _item("standin", "麵包發酵筆記", "老麵種的養法")
    store_item_embedding(stand_in, _deterministic_local_embedding(stand_in_text), model=LOCAL_EMBEDDING_MODEL)
    return stand_in


def test_a_fallback_query_is_not_answered_from_the_few_stand_in_rows(monkeypatch):
    # The stand-in row is as close to the hashed query vector as a row can be (the same
    # numbers), and its words have nothing to do with the query.
    stand_in = _mostly_real_index(stand_in_text="語音轉錄工具")
    wanted = _item("wanted", "語音轉錄工具", "會議錄音轉文字")
    _real_model_is_configured(monkeypatch, answers=False)

    results = asyncio.run(search_hybrid("語音轉錄工具", limit=5))

    assert results.semantic["state"] == "unavailable"
    assert results.semantic["reason"] == "embedding_unreachable"
    assert [r["id"] for r in results] == [wanted]  # keywords only
    assert stand_in not in [r["id"] for r in results]
    assert all(r["vec_rank"] is None for r in results)


def test_a_query_from_the_minority_model_is_keyword_only(monkeypatch):
    stand_in = _mostly_real_index()  # no real model configured: the hashed vectors are the query's own

    results = asyncio.run(search_hybrid("麵包發酵筆記 老麵種的養法", limit=5))

    assert results.semantic == {"state": "unavailable", "reason": "model_mismatch",
                                "query_model": LOCAL_EMBEDDING_MODEL, "index_model": REAL_MODEL,
                                "indexed": 1, "not_indexed": 3}
    assert [r["id"] for r in results] == [stand_in]  # found by its words
    assert results[0]["vec_rank"] is None and results[0]["similarity"] == 0.0


def test_the_majority_model_still_searches_and_reports_what_it_cannot_reach(monkeypatch):
    _mostly_real_index()
    _real_model_is_configured(monkeypatch, answers=True)

    results = asyncio.run(search_hybrid("anything", limit=5))

    assert results.semantic["state"] == "partial" and results.semantic["not_indexed"] == 1
    assert results[0]["vec_rank"] == 1 and results[0]["title_l1"] == "向量資料庫比較 0"


def test_a_fully_local_index_keeps_its_semantic_side():
    item_id = _item("local", "SQLite vector search extensions")
    store_item_embedding(item_id, _deterministic_local_embedding("SQLite vector search extensions"),
                         model=LOCAL_EMBEDDING_MODEL)
    results = asyncio.run(search_hybrid("SQLite vector search", limit=5))
    assert results.semantic["state"] == "ok"
    assert results[0]["id"] == item_id and results[0]["vec_rank"] == 1


def test_the_skipped_semantic_side_is_logged_again_later(monkeypatch, caplog):
    _mostly_real_index()

    def warnings():
        return [r for r in caplog.records if "Semantic search is skipped" in r.getMessage()]

    with caplog.at_level(logging.WARNING, logger="omnikeep.vector"):
        asyncio.run(search_hybrid("麵包", limit=5))
        asyncio.run(search_hybrid("麵包", limit=5))
        assert len(warnings()) == 1  # not once per query
        clock = vector.time.monotonic()
        monkeypatch.setattr(vector.time, "monotonic", lambda: clock + vector.WARN_AGAIN_AFTER + 1)
        asyncio.run(search_hybrid("麵包", limit=5))
        assert len(warnings()) == 2  # but not once per process either


def test_a_runner_that_gives_no_embedding_is_logged_as_a_warning(monkeypatch, caplog):
    import httpx

    class _Down:
        def __init__(self, *args, **kwargs):
            assert kwargs["timeout"] == vector.OLLAMA_EMBED_TIMEOUT >= 30  # room for loading the model

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(httpx, "AsyncClient", _Down)
    with caplog.at_level(logging.WARNING, logger="omnikeep.vector"):
        assert asyncio.run(vector._ollama_embedding("text", 256, True)) is None
    assert any("gave no embedding (ReadTimeout)" in r.getMessage() for r in caplog.records)


# ── Indexing while the model is down ────────────────────────────

def _index_like_the_pipeline(item_id, text) -> bool:
    vec, model = asyncio.run(vector.generate_embedding_with_model(text))
    return store_item_embedding(item_id, vec, model=model)


def test_no_stand_in_vector_is_stored_while_the_real_model_is_down(monkeypatch):
    item_id = _item("new", "語音轉錄工具")
    _real_model_is_configured(monkeypatch, answers=False)

    assert _index_like_the_pipeline(item_id, "語音轉錄工具") is False
    assert get_item_embedding(item_id) is None
    assert reindex.pending_item_ids() == [item_id]
    # Still down: the backfill writes nothing.
    assert asyncio.run(reindex.backfill_pending())["reembedded"] == 0
    assert get_item_embedding(item_id) is None


def test_an_older_vector_is_kept_while_the_real_model_is_down(monkeypatch):
    item_id = _item("old", "語音轉錄工具")
    store_item_embedding(item_id, _real_vector(3), model=REAL_MODEL)
    _real_model_is_configured(monkeypatch, answers=False)
    assert _index_like_the_pipeline(item_id, "語音轉錄工具，新摘要") is False
    assert get_item_embedding(item_id) == _real_vector(3)
    assert reindex.pending_item_ids() == []


def test_hashed_vectors_are_stored_when_they_are_the_configured_choice():
    item_id = _item("local", "語音轉錄工具")
    assert _index_like_the_pipeline(item_id, "語音轉錄工具") is True
    assert get_item_embedding(item_id) is not None
    assert reindex.pending_item_ids() == []  # nothing to wait for


def test_the_backfill_embeds_what_waited_once_the_model_answers(monkeypatch):
    waiting = _item("waiting", "語音轉錄工具", day=3)
    stand_in = _item("standin", "麵包發酵筆記", day=2)
    store_item_embedding(stand_in, _deterministic_local_embedding("麵包發酵筆記"), model=LOCAL_EMBEDDING_MODEL)
    done = _item("done", "向量資料庫比較", day=1)
    store_item_embedding(done, _real_vector(5), model=REAL_MODEL)
    stub = _item("stub", "尚未分析的雷達項目", analysis_status="pending")
    _real_model_is_configured(monkeypatch, answers=True)

    assert reindex.pending_item_ids() == [waiting, stand_in]
    stats = asyncio.run(reindex.backfill_pending())

    assert stats == {"pending": 2, "reembedded": 2, "fell_back": 0, "stopped": None}
    assert reindex.pending_item_ids() == []
    assert vector.index_model_counts() == {REAL_MODEL: 3}
    assert get_item_embedding(done) == _real_vector(5)  # untouched
    assert get_item_embedding(stub) is None  # indexed when it is analysed, like any new item


# ── What the person is told ─────────────────────────────────────

class _Chat:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        class _Response:
            status_code = 200

            def json(self):
                return {"message": {"content": "依據文獻 [1] 的回答"}}
        return _Response()


def test_the_answer_says_when_semantic_search_took_no_part(monkeypatch):
    stand_in = _mostly_real_index()
    wanted = _item("wanted", "會議錄音工具", "本機語音轉錄，不上傳雲端")
    _real_model_is_configured(monkeypatch, answers=False)
    monkeypatch.setattr(brain.httpx, "AsyncClient", _Chat)

    res = asyncio.run(brain.ask_brain(QUESTION))

    assert [c["id"] for c in res["citations"]] == [wanted]
    assert stand_in not in [c["id"] for c in res["citations"]]
    assert res["retrieval"]["semantic"] == "unavailable"
    assert res["notice"] == brain.SEMANTIC_OFF_NOTICES["embedding_unreachable"]
    assert "語意搜尋目前沒有運作" in res["notice"] and "關鍵字" in res["notice"]


def test_no_notice_when_semantic_search_worked(monkeypatch):
    item_id = _item("local", "語音轉錄工具")
    store_item_embedding(item_id, _deterministic_local_embedding("語音轉錄工具"), model=LOCAL_EMBEDDING_MODEL)
    monkeypatch.setattr(brain.httpx, "AsyncClient", _Chat)
    res = asyncio.run(brain.ask_brain("語音轉錄工具"))
    assert res["notice"] == "" and res["retrieval"]["semantic"] == "ok"
    assert res["citations"][0]["id"] == item_id


def test_an_agent_is_told_too(monkeypatch):
    _mostly_real_index()
    _item("wanted", "會議錄音工具", "本機語音轉錄，不上傳雲端")
    _real_model_is_configured(monkeypatch, answers=False)
    found = asyncio.run(mcp_server.hybrid_search_brain(QUESTION))
    assert "會議錄音工具" in found and "【關鍵字檢索】" in found
    assert "語意搜尋目前沒有運作" in found
    nothing = asyncio.run(mcp_server.hybrid_search_brain("zzzz-no-such-thing"))
    assert "找不到" in nothing and "語意搜尋目前沒有運作" in nothing


# ── Items with nothing to cite ──────────────────────────────────

def _items_with_nothing_to_cite():
    from app.pipeline import FETCH_FAILED_TAG
    failed = _item("failed", "ask.test/failed", f"{FETCH_FAILED_TAG}語音轉錄頁面打不開，稍後會自動重抓。")
    quarantined = _item("junk", "無效內容", "語音轉錄：輸入內容只有導覽列", category_name="隔離區")
    pending = _item("stub", "語音轉錄新聞", "語音轉錄", analysis_status="pending")
    return failed, quarantined, pending


def test_an_answer_leaves_out_items_with_nothing_to_cite(monkeypatch):
    junk = _items_with_nothing_to_cite()
    wanted = _item("wanted", "會議錄音工具", "本機語音轉錄，不上傳雲端")
    monkeypatch.setattr(brain.httpx, "AsyncClient", _Chat)

    res = asyncio.run(brain.ask_brain(QUESTION))

    cited = [c["id"] for c in res["citations"]]
    assert cited == [wanted]
    assert not set(junk) & set(cited)


def test_the_search_box_still_lists_them():
    junk = _items_with_nothing_to_cite()
    found = {row["id"] for row in get_items(query="語音轉錄", limit=50)}
    assert set(junk) <= found
    plain = asyncio.run(search_hybrid("語音轉錄", limit=10))
    assert set(junk) <= {r["id"] for r in plain}


def test_an_agent_is_not_given_them_either():
    _items_with_nothing_to_cite()
    _item("wanted", "會議錄音工具", "本機語音轉錄，不上傳雲端")
    found = asyncio.run(mcp_server.hybrid_search_brain("語音轉錄"))
    assert "會議錄音工具" in found
    assert "無效內容" not in found and "ask.test/failed" not in found and "語音轉錄新聞" not in found
