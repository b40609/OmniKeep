import sqlite3
import json
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.config import settings

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Categories table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            icon TEXT DEFAULT 'tag',
            sort_order INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # 2. Default categories seed
    default_categories = ["AI", "加密貨幣", "台股", "Github", "時事", "旅遊", "美食"]
    for idx, cat_name in enumerate(default_categories):
        cursor.execute("""
            INSERT OR IGNORE INTO categories (name, sort_order)
            VALUES (?, ?)
        """, (cat_name, idx))
    
    # 3. Items table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            url TEXT UNIQUE NOT NULL,
            source_type TEXT NOT NULL,
            category_name TEXT DEFAULT 'Inbox',
            title_l1 TEXT NOT NULL,
            summary_l1 TEXT NOT NULL,
            tech_tags TEXT NOT NULL,
            deep_analysis TEXT,
            content_raw TEXT,
            author TEXT,
            published_date TEXT,
            cover_image TEXT,
            is_starred INTEGER DEFAULT 0,
            is_read INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 4. Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_category ON items(category_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_created ON items(created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_starred ON items(is_starred)")

    # 5. FTS5 Virtual Table for full-text search
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
            id UNINDEXED,
            title_l1,
            summary_l1,
            tech_tags,
            deep_analysis,
            content_raw,
            tokenize='unicode61'
        )
    """)

    # 6. Triggers to keep FTS in sync
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
            INSERT INTO items_fts(id, title_l1, summary_l1, tech_tags, deep_analysis, content_raw)
            VALUES (new.id, new.title_l1, new.summary_l1, new.tech_tags, new.deep_analysis, new.content_raw);
        END;
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
            DELETE FROM items_fts WHERE id = old.id;
        END;
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
            DELETE FROM items_fts WHERE id = old.id;
            INSERT INTO items_fts(id, title_l1, summary_l1, tech_tags, deep_analysis, content_raw)
            VALUES (new.id, new.title_l1, new.summary_l1, new.tech_tags, new.deep_analysis, new.content_raw);
        END;
    """)

    conn.commit()
    conn.close()

# ── Categories DAO ──────────────────────────────────────────────

def get_all_categories() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    # Also fetch count of items for each category
    cursor.execute("""
        SELECT c.id, c.name, c.icon, c.sort_order, COUNT(i.id) AS item_count
        FROM categories c
        LEFT JOIN items i ON i.category_name = c.name
        GROUP BY c.id
        ORDER BY c.sort_order ASC, c.name ASC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

def add_category(name: str, icon: str = "tag") -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO categories (name, icon) VALUES (?, ?)", (name.strip(), icon))
        conn.commit()
        cat_id = cursor.lastrowid
        conn.close()
        return {"id": cat_id, "name": name.strip(), "icon": icon, "item_count": 0}
    except sqlite3.IntegrityError:
        conn.close()
        return None

def delete_category(name: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    # Move items to 'Inbox'
    cursor.execute("UPDATE items SET category_name = 'Inbox' WHERE category_name = ?", (name,))
    cursor.execute("DELETE FROM categories WHERE name = ?", (name,))
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

# ── Items DAO ───────────────────────────────────────────────────

def save_item(item_data: Dict[str, Any]) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    item_id = item_data.get("id") or uuid.uuid4().hex[:12]
    now = datetime.utcnow().isoformat()
    
    tags = item_data.get("tech_tags", [])
    if isinstance(tags, list):
        tags_str = json.dumps(tags, ensure_ascii=False)
    else:
        tags_str = str(tags)

    cursor.execute("""
        INSERT INTO items (
            id, url, source_type, category_name, title_l1, summary_l1,
            tech_tags, deep_analysis, content_raw, author, published_date,
            cover_image, is_starred, is_read, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            category_name = excluded.category_name,
            title_l1 = excluded.title_l1,
            summary_l1 = excluded.summary_l1,
            tech_tags = excluded.tech_tags,
            deep_analysis = excluded.deep_analysis,
            content_raw = excluded.content_raw,
            updated_at = excluded.updated_at
    """, (
        item_id,
        item_data["url"],
        item_data.get("source_type", "web"),
        item_data.get("category_name", "Inbox"),
        item_data.get("title_l1", "未命名項目"),
        item_data.get("summary_l1", ""),
        tags_str,
        item_data.get("deep_analysis", ""),
        item_data.get("content_raw", ""),
        item_data.get("author", ""),
        item_data.get("published_date", ""),
        item_data.get("cover_image", ""),
        item_data.get("is_starred", 0),
        item_data.get("is_read", 0),
        now,
        now
    ))
    conn.commit()
    conn.close()
    return item_id

def get_items(
    category: Optional[str] = None,
    query: Optional[str] = None,
    is_starred: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if query and query.strip():
        # FTS query
        clean_q = query.strip().replace('"', '""')
        fts_query = f'"{clean_q}"*'
        sql = """
            SELECT i.* FROM items i
            JOIN items_fts f ON i.id = f.id
            WHERE items_fts MATCH ?
        """
        params = [fts_query]
        if category and category != "全部":
            sql += " AND i.category_name = ?"
            params.append(category)
        if is_starred is not None:
            sql += " AND i.is_starred = ?"
            params.append(1 if is_starred else 0)
        sql += " ORDER BY i.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(sql, params)
    else:
        sql = "SELECT * FROM items WHERE 1=1"
        params = []
        if category and category != "全部":
            sql += " AND category_name = ?"
            params.append(category)
        if is_starred is not None:
            sql += " AND is_starred = ?"
            params.append(1 if is_starred else 0)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(sql, params)

    rows = []
    for r in cursor.fetchall():
        d = dict(r)
        try:
            d["tech_tags"] = json.loads(d["tech_tags"])
        except Exception:
            d["tech_tags"] = []
        rows.append(d)
        
    conn.close()
    return rows

def get_item_by_id(item_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM items WHERE id = ?", (item_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["tech_tags"] = json.loads(d["tech_tags"])
    except Exception:
        d["tech_tags"] = []
    return d

def update_item_field(item_id: str, updates: Dict[str, Any]) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    updates["updated_at"] = datetime.utcnow().isoformat()
    fields = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [item_id]
    cursor.execute(f"UPDATE items SET {fields} WHERE id = ?", values)
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok

def delete_item(item_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM items WHERE id = ?", (item_id,))
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok
