"""Chinese full-text search: words inside a sentence are found (trigram index + LIKE for short words)."""
from contextlib import closing

from app import database
from app.database import get_db_connection, get_items, save_item


def _item(url, title, summary, content="", tags=("AI",)):
    return save_item({"url": url, "source_type": "web", "title_l1": title, "summary_l1": summary,
                      "tech_tags": list(tags), "deep_analysis": "", "content_raw": content})


def _ids(query):
    return {row["id"] for row in get_items(query=query, limit=50)}


def test_the_index_uses_the_trigram_tokenizer():
    with closing(get_db_connection()) as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'items_fts'").fetchone()[0]
    assert "trigram" in sql


def test_chinese_words_inside_a_sentence_are_found():
    a = _item("https://a.test/1", "邊緣推論的時序資料庫實測", "在產線設備上跑本機模型")
    b = _item("https://a.test/2", "量化交易回測框架", "用向量化計算加速回測")
    assert _ids("推論") == {a}                # two characters: LIKE path
    assert _ids("時序資料") == {a}            # four characters inside the title: trigram path
    assert _ids("向量化") == {b}
    assert _ids("推論 回測") == {a, b}        # no item holds both words, so either one is enough


def test_raw_content_and_english_substrings_are_searched():
    a = _item("https://a.test/3", "Release notes", "short", content="新增 FastAPI 的串流回應與向量檢索")
    assert _ids("串流") == {a}
    assert _ids("fastapi") == {a}             # case-insensitive substring
    assert _ids("向量檢索") == {a}


def test_an_old_unicode61_index_is_rebuilt_with_existing_items():
    a = _item("https://a.test/4", "多語向量模型評測", "Qwen3 Embedding")
    with closing(get_db_connection()) as db, db:
        db.execute("DROP TABLE items_fts")
        db.execute("CREATE VIRTUAL TABLE items_fts USING fts5(id UNINDEXED, title_l1, summary_l1, tech_tags, "
                   "deep_analysis, content_raw, tokenize='unicode61')")
    database.init_db()
    with closing(get_db_connection()) as db:
        sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'items_fts'").fetchone()[0]
        rows = db.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0]
    assert "trigram" in sql and rows >= 1
    assert _ids("向量模型") == {a}


def test_new_and_updated_items_stay_in_sync():
    a = _item("https://a.test/5", "舊標題", "摘要")
    with closing(get_db_connection()) as db, db:
        db.execute("UPDATE items SET title_l1 = ? WHERE id = ?", ("改過的知識圖譜標題", a))
    assert _ids("知識圖譜") == {a}
    assert _ids("舊標題") == set()
