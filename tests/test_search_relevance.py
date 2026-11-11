"""Search asks for every word, widens to any word only when nothing holds them all, and
puts the best match first (bm25 with column weights; for short words, the column they are in)."""
import asyncio
from contextlib import closing

import pytest

from app import database
from app.config import settings
from app.database import get_db_connection, get_items, save_item, search_words


def _item(name, title, summary="摘要", tags=(), deep="", content="", day=1, **extra):
    """An item whose age is set by `day`: a higher day is newer."""
    item_id = save_item({"url": f"https://search.test/{name}", "title_l1": title, "summary_l1": summary,
                         "tech_tags": list(tags), "deep_analysis": deep, "content_raw": content, **extra})
    with closing(get_db_connection()) as db, db:
        db.execute("UPDATE items SET created_at = ? WHERE id = ?", (f"2026-01-{day:02d}T00:00:00+00:00", item_id))
    return item_id


def _found(query, **filters):
    return [row["id"] for row in get_items(query=query, limit=50, **filters)]


def test_every_word_has_to_be_found():
    both = _item("both", "Kubernetes 上的 PostgreSQL 高可用", "用 operator 管理叢集")
    _item("first", "Kubernetes 排程器原理", "pod 如何被指派到節點")
    _item("second", "PostgreSQL 索引調校", "B-tree 與 GIN")
    assert _found("Kubernetes PostgreSQL") == [both]
    # The words may sit in different columns of the same item.
    assert _found("Kubernetes operator") == [both]


def test_a_short_word_no_longer_brings_in_everything_that_contains_it():
    wanted = _item("wanted", "AI agent 框架比較", "三種代理框架")
    _item("mail", "Email 行銷自動化", "寄送排程")            # holds "ai" inside "Email", no agent
    _item("agents", "agent 設計模式", "工具呼叫與規劃")       # holds agent, no "ai"
    assert _found("AI agent") == [wanted]


def test_any_word_is_enough_only_when_no_item_holds_them_all():
    two = _item("two", "Kubernetes 上的 PostgreSQL", "叢集", day=1)
    one = _item("one", "SQLite 快取策略", "淘汰機制", day=2)
    other = _item("other", "Kubernetes 網路模型", "CNI", day=3)
    # No item holds all three words: the one with two of them leads, though it is the oldest.
    found = _found("Kubernetes PostgreSQL SQLite")
    assert found[0] == two and set(found[1:]) == {one, other}
    # As soon as one item holds them all, the others are left out again.
    assert _found("Kubernetes PostgreSQL") == [two]


def test_widening_happens_inside_the_active_filters():
    starred = _item("starred", "Kubernetes 排程器", "節點", is_starred=1)
    _item("plain", "Kubernetes 上的 PostgreSQL", "叢集")
    # Among starred items nothing holds both words, so any word is enough there.
    assert _found("Kubernetes PostgreSQL", is_starred=True) == [starred]


def test_a_title_match_comes_before_a_match_in_the_raw_content_only():
    in_title = _item("title", "Speculative decoding 加速推理", "草稿模型先猜", day=1)
    in_content = _item("content", "週報第 12 期", "本週摘要", day=9,
                       content="文末順帶提到 speculative decoding 一次。" + "其他內容。" * 40)
    assert _found("speculative") == [in_title, in_content]  # the newer item no longer wins
    assert _found("speculative decoding") == [in_title, in_content]


def test_short_words_rank_by_the_column_they_are_found_in_then_by_age():
    content = _item("content", "週報", "本週", content="提到推論一次", day=9)
    deep = _item("deep", "筆記", "隨手記", deep="## 推論成本", day=8)
    tags = _item("tags", "模型部署", "上線流程", tags=["推論"], day=7)
    summary = _item("summary", "邊緣裝置", "在邊緣做推論", day=6)
    older_title = _item("title-old", "推論伺服器比較", "三套方案", day=1)
    newer_title = _item("title-new", "本機推論入門", "從零開始", day=2)
    assert _found("推論") == [newer_title, older_title, summary, tags, deep, content]


def test_two_character_chinese_words_are_found_and_all_required():
    both = _item("both", "邊緣推論的時序資料庫", "在產線設備上跑模型")
    _item("one", "量化交易回測", "推論速度不是重點")
    assert _found("推論 邊緣") == [both]
    assert _found("邊緣") == [both]


def test_chinese_and_english_words_mix_and_both_shape_the_order():
    # Every item holds "向量" (two characters: LIKE) and "sqlite" (trigram index).
    best = _item("best", "SQLite 向量搜尋實作", "sqlite-vec 筆記", day=1)
    weaker = _item("weaker", "SQLite 效能調校", "WAL 與索引", content="順帶提到向量一次", day=2)
    weakest = _item("weakest", "週報", "雜項", content="這期有 sqlite 也有向量", day=3)
    _item("unrelated", "SQLite 備份", "線上備份 API", day=4)  # no "向量": left out
    assert _found("向量 SQLite") == [best, weaker, weakest]
    assert _found("SQLite 向量") == [best, weaker, weakest]


@pytest.mark.parametrize("query", [
    '"', '""', '"unterminated', 'a "quoted phrase" b', "it's", "'; DROP TABLE items; --",
    "C++", "100%", "snake_case", "%", "_", "~", "(paren", "star*", "col:on", "a AND b", "NOT", "NEAR(a b)",
    "-minus", "^caret", "back\\slash", "nul\x00byte", "emoji 👍", "   ", "全形　空白",
])
def test_quotes_and_special_characters_never_break_the_query(query):
    _item("plain", "一般項目", "沒有特別的字")
    rows = get_items(query=query, limit=50)
    assert isinstance(rows, list)
    with closing(get_db_connection()) as db:
        assert db.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1  # and nothing was run as SQL


def test_like_wildcards_in_a_short_word_are_literal_text():
    percent = _item("percent", "折扣 5% 起", "促銷")
    _item("plain", "一般項目", "沒有特別的字")
    assert _found("%") == [percent]
    assert _found("_") == []
    assert _found("5%") == [percent]


def test_words_with_punctuation_inside_are_searched_as_written():
    cpp = _item("cpp", "C++ 模板技巧", "SFINAE 與 concepts")
    _item("c", "C 語言指標", "記憶體配置")
    assert _found("C++") == [cpp]
    assert search_words('"C++"  c++ "模板"') == ["C++", "模板"]  # quotes dropped, repeats merged


def test_a_query_without_words_lists_like_no_query():
    old = _item("old", "舊的", day=1)
    new = _item("new", "新的", day=2)
    assert _found('""') == [new, old]
    assert [row["id"] for row in get_items(limit=50)] == [new, old]  # the plain list stays newest first


def test_pages_stay_in_one_mode():
    full = _item("full", "Kubernetes 上的 PostgreSQL", "叢集", day=1)
    _item("part", "Kubernetes 網路模型", "CNI", day=2)
    assert [r["id"] for r in get_items(query="Kubernetes PostgreSQL", limit=1, offset=0)] == [full]
    # Page 2 of the all-words results is empty; it must not switch to any-word results.
    assert get_items(query="Kubernetes PostgreSQL", limit=1, offset=1) == []


def test_search_survives_a_broken_full_text_index():
    title = _item("title", "Kubernetes 排程器", "節點", day=1)
    content = _item("content", "週報", "雜項", content="kubernetes 一次", day=2)
    with closing(get_db_connection()) as db, db:
        db.execute("DROP TABLE items_fts")
    # Every word is then found with LIKE and ranked by column.
    assert _found("Kubernetes") == [title, content]
    assert _found("Kubernetes 節點") == [title]


def test_hybrid_search_takes_its_lexical_rank_from_relevance(monkeypatch):
    from app.vector import search_hybrid
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    in_title = _item("title", "Speculative decoding 加速推理", "草稿模型先猜", day=1)
    in_content = _item("content", "週報第 12 期", "本週摘要", day=9,
                       content="文末順帶提到 speculative decoding 一次。" + "其他內容。" * 40)
    results = asyncio.run(search_hybrid("speculative decoding", limit=5))  # no vectors stored: lexical only
    ranks = {r["id"]: r["fts_rank"] for r in results}
    assert ranks == {in_title: 1, in_content: 2}
    assert [r["id"] for r in results] == [in_title, in_content]


def test_related_items_fall_back_to_a_tag_search_that_needs_the_whole_tag():
    current = _item("current", "向量索引筆記", "摘要", tags=["Vector Search"])
    match = _item("match", "Vector search 的近似演算法", "HNSW 與 IVF")
    _item("partial", "Search 介面設計", "篩選與排序")
    related = database.get_related_items(current, limit=4)
    assert [r["id"] for r in related] == [match]
