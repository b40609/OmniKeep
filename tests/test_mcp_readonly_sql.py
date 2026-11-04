"""read_sql_query must not be able to change the database, whatever the statement
looks like. A first-word check alone let CTE writes and PRAGMA assignments through."""
import asyncio
from contextlib import closing

import pytest

from app.database import get_db_connection, save_item
from app.mcp_server import read_sql_query


def _snapshot():
    with closing(get_db_connection()) as conn:
        return (
            conn.execute("SELECT COUNT(*) FROM items").fetchone()[0],
            [r[0] for r in conn.execute("SELECT title_l1 FROM items ORDER BY id")],
            conn.execute("PRAGMA user_version").fetchone()[0],
        )


def test_read_sql_query_returns_rows():
    save_item({"url": "https://example.test/ro-read", "title_l1": "唯讀查詢測試"})
    out = asyncio.run(read_sql_query("SELECT title_l1 FROM items"))
    assert "唯讀查詢測試" in out


@pytest.mark.parametrize("sql", [
    "WITH x AS (SELECT 1) DELETE FROM items -- LIMIT",
    "WITH x AS (SELECT 1) UPDATE items SET title_l1 = 'changed' -- LIMIT",
    "WITH x AS (SELECT 1) INSERT INTO categories (name) VALUES ('injected') -- LIMIT",
    "PRAGMA user_version = 42",
    "DELETE FROM items",
])
def test_read_sql_query_cannot_write(sql):
    save_item({"url": "https://example.test/ro-write", "title_l1": "不可被改"})
    before = _snapshot()
    out = asyncio.run(read_sql_query(sql))
    assert _snapshot() == before
    assert "錯誤" in out
    with closing(get_db_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM categories WHERE name = 'injected'").fetchone()[0] == 0
