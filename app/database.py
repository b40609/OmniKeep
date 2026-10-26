import sqlite3
import json
import uuid
import re
from contextlib import closing
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from app.config import settings

def get_db_connection() -> sqlite3.Connection:
    import os
    if os.environ.get("OMNIKEEP_TESTING") == "1":
        root = Path(os.environ["OMNIKEEP_TEST_ROOT"]).resolve()
        if not Path(settings.DATABASE_PATH).resolve().is_relative_to(root):
            raise RuntimeError("Tests must use an isolated database")
    conn = sqlite3.connect(settings.DATABASE_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA cache_size = -64000")  # 64MB memory page cache
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
    default_categories = ["AI", "加密貨幣", "台股", "Github", "時事", "旅遊", "美食", "監看", "提案"]
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
            analysis_status TEXT NOT NULL DEFAULT 'done',
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

    # 7. Radar Subscriptions table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS radar_sources (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            source_type TEXT NOT NULL,
            url TEXT NOT NULL,
            tier INTEGER DEFAULT 2,
            hot_hours TEXT DEFAULT '[]',
            check_interval_minutes INTEGER DEFAULT 60,
            last_fetched_at TEXT,
            last_published_at TEXT,
            etag TEXT,
            last_modified_header TEXT,
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 8. User Topic Weights table (Signal Tuner: Boost / Dampen / Mute)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_topic_weights (
            topic_tag TEXT PRIMARY KEY,
            weight REAL DEFAULT 1.0,
            boost_count INTEGER DEFAULT 0,
            dampen_count INTEGER DEFAULT 0,
            is_blocked INTEGER DEFAULT 0,
            last_interacted_at TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 9. Radar Events table (Cross-source deduplication & clustering)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS radar_events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            primary_item_id TEXT NOT NULL,
            related_item_ids TEXT DEFAULT '[]',
            unique_source_count INTEGER DEFAULT 1,
            score REAL DEFAULT 1.0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 10. Radar Digests table (Batched multi-source digests)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS radar_digests (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            digest_type TEXT NOT NULL,
            markdown_content TEXT NOT NULL,
            item_ids TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 11. Item Citations table (Entity Fan-out & Linking)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS item_citations (
            id TEXT PRIMARY KEY,
            target_item_id TEXT,
            source_parent_id TEXT NOT NULL,
            target_canonical_url TEXT NOT NULL,
            target_name TEXT NOT NULL,
            mention_context TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(source_parent_id) REFERENCES items(id) ON DELETE CASCADE,
            FOREIGN KEY(target_item_id) REFERENCES items(id) ON DELETE SET NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citations_target ON item_citations(target_item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citations_parent ON item_citations(source_parent_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_citations_canonical ON item_citations(target_canonical_url)")

    # 12. Ingest Tasks table (Persistent Task Queue / Hoarder Pattern)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ingest_tasks (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            source TEXT DEFAULT 'telegram',
            chat_id TEXT,
            message_id INTEGER,
            status TEXT NOT NULL DEFAULT 'queued',
            error_message TEXT,
            item_id TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON ingest_tasks(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON ingest_tasks(created_at ASC)")

    # 13. User Settings table (Per-user preference persistence)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id TEXT PRIMARY KEY,
            interaction_mode TEXT DEFAULT 'heartbeat',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 14. Watch Targets table (Local Proposal Engine: what OmniKeep may watch & how much)
    # Two independent permission axes, stored as JSON toggle maps:
    #   read_scope         — what the LOCAL scanner may read from disk
    #   outbound_consent   — what may be SENT to the cloud LLM (Agnes) for analysis
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watch_targets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT 'folder',
            path TEXT NOT NULL,
            preset TEXT DEFAULT 'balanced',
            read_scope TEXT NOT NULL DEFAULT '{}',
            outbound_consent TEXT NOT NULL DEFAULT '{}',
            is_active INTEGER DEFAULT 1,
            last_scan_at TEXT,
            fingerprint_item_id TEXT,
            fingerprint_version TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 15. Proposals table (glass-box suggestion cards; card text lives in items/提案)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS proposals (
            id TEXT PRIMARY KEY,
            item_id TEXT NOT NULL,
            target_id TEXT,
            proposal_type TEXT NOT NULL DEFAULT 'risk',
            impact REAL DEFAULT 5.0,
            confidence REAL DEFAULT 5.0,
            effort REAL DEFAULT 5.0,
            user_impact REAL,
            user_confidence REAL,
            user_effort REAL,
            correction_reason TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            decided_at TEXT,
            dedup_key TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_proposals_dedup ON proposals(dedup_key)")

    # 16. Backup Runs table (multi-sink backup audit trail)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backup_runs (
            id TEXT PRIMARY KEY,
            sink TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'ok',
            file_path TEXT,
            size_bytes INTEGER,
            error TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 17. Behavior Events table (P1: swipe/click/view fuel for the future
    # local preference model — content stays in items, behavior lives here)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS behavior_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            item_id TEXT,
            proposal_id TEXT,
            source TEXT DEFAULT 'api',
            meta TEXT DEFAULT '{}',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_behavior_item ON behavior_events(item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_behavior_type ON behavior_events(event_type)")

    # 18. items.origin migration (radar | manual | agent | watch | proposal)
    cursor.execute("PRAGMA table_info(items)")
    item_cols = {row[1] for row in cursor.fetchall()}
    if "origin" not in item_cols:
        cursor.execute("ALTER TABLE items ADD COLUMN origin TEXT DEFAULT 'manual'")
    # analysis_status: 'pending' = radar stub saved past the per-cycle LLM
    # budget, awaiting backfill; 'done' = fully analyzed.
    if "analysis_status" not in item_cols:
        cursor.execute("ALTER TABLE items ADD COLUMN analysis_status TEXT NOT NULL DEFAULT 'done'")

    # 19. Interest profile (free text woven into analysis/digest prompts)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_interest_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            profile_text TEXT NOT NULL DEFAULT '',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 20. Dream Pass Proposals (self-reflection on user behavior)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profile_dreampass_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'pending',
            observations TEXT NOT NULL,
            suggested_profile TEXT NOT NULL,
            diff_summary TEXT NOT NULL,
            current_profile TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL,
            applied_at DATETIME
        )
    """)

    # 21. Hard Rules Engine (Karakeep pattern: deterministic automation)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 10,
            field TEXT NOT NULL,
            operator TEXT NOT NULL,
            value TEXT NOT NULL,
            action_type TEXT NOT NULL,
            action_value TEXT NOT NULL DEFAULT '',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """)

    conn.commit()
    conn.close()

    try:
        from app.vector import init_vector_db
        init_vector_db()
    except Exception:
        pass

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
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        return _save_item(conn, item_data)


def _save_item(conn, item_data: Dict[str, Any]) -> str:
    cursor = conn.cursor()
    
    # Check if url already exists to preserve and return the true existing item id
    cursor.execute("SELECT id FROM items WHERE url = ? LIMIT 1", (item_data["url"],))
    existing_row = cursor.fetchone()
    if existing_row:
        item_id = existing_row["id"]
    else:
        item_id = item_data.get("id") or uuid.uuid4().hex[:12]

    now = datetime.now(timezone.utc).isoformat()
    
    tags = item_data.get("tech_tags", [])
    if isinstance(tags, list):
        tags_str = json.dumps(tags, ensure_ascii=False)
    else:
        tags_str = str(tags)

    cursor.execute("""
        INSERT INTO items (
            id, url, source_type, category_name, title_l1, summary_l1,
            tech_tags, deep_analysis, content_raw, author, published_date,
            cover_image, is_starred, is_read, analysis_status, origin, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            category_name = excluded.category_name,
            title_l1 = excluded.title_l1,
            summary_l1 = excluded.summary_l1,
            tech_tags = excluded.tech_tags,
            deep_analysis = excluded.deep_analysis,
            content_raw = excluded.content_raw,
            analysis_status = excluded.analysis_status,
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
        item_data.get("analysis_status", "done"),
        item_data.get("origin", "manual"),
        now,
        now
    ))
    return item_id

def get_items(
    category: Optional[str] = None,
    query: Optional[str] = None,
    is_starred: Optional[bool] = None,
    is_read: Optional[bool] = None,
    origin: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if query and query.strip():
        # FTS query with multi-term OR search & graceful LIKE fallback
        clean_q = query.strip().replace('"', '')
        words = [w.strip() for w in clean_q.split() if w.strip()]
        if len(words) > 1:
            fts_query = " OR ".join([f'"{w}"*' for w in words])
        else:
            fts_query = f'"{clean_q}"*'
            
        sql = """
            SELECT i.*,
                   (SELECT COUNT(*) FROM item_citations WHERE target_item_id = i.id) AS citations_count,
                   (SELECT COUNT(*) FROM item_citations WHERE source_parent_id = i.id) AS sub_entities_count
            FROM items i
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
        if is_read is not None:
            sql += " AND i.is_read = ?"
            params.append(1 if is_read else 0)
        if origin:
            sql += " AND i.origin = ?"
            params.append(origin)
        sql += " ORDER BY i.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        try:
            cursor.execute(sql, params)
            db_rows = cursor.fetchall()
        except Exception:
            db_rows = []

        if not db_rows:
            # Fallback to LIKE matching
            fallback_sql = """
                SELECT i.*,
                       (SELECT COUNT(*) FROM item_citations WHERE target_item_id = i.id) AS citations_count,
                       (SELECT COUNT(*) FROM item_citations WHERE source_parent_id = i.id) AS sub_entities_count
                FROM items i
                WHERE (i.title_l1 LIKE ? OR i.summary_l1 LIKE ? OR i.tech_tags LIKE ? OR i.deep_analysis LIKE ?)
            """
            like_param = f"%{clean_q}%"
            f_params = [like_param, like_param, like_param, like_param]
            if category and category != "全部":
                fallback_sql += " AND i.category_name = ?"
                f_params.append(category)
            if is_starred is not None:
                fallback_sql += " AND i.is_starred = ?"
                f_params.append(1 if is_starred else 0)
            if is_read is not None:
                fallback_sql += " AND i.is_read = ?"
                f_params.append(1 if is_read else 0)
            if origin:
                fallback_sql += " AND i.origin = ?"
                f_params.append(origin)
            fallback_sql += " ORDER BY i.created_at DESC LIMIT ? OFFSET ?"
            f_params.extend([limit, offset])
            cursor.execute(fallback_sql, f_params)
            db_rows = cursor.fetchall()
    else:
        sql = """
            SELECT i.*,
                   (SELECT COUNT(*) FROM item_citations WHERE target_item_id = i.id) AS citations_count,
                   (SELECT COUNT(*) FROM item_citations WHERE source_parent_id = i.id) AS sub_entities_count
            FROM items i
            WHERE 1=1
        """
        params = []
        if category and category != "全部":
            sql += " AND i.category_name = ?"
            params.append(category)
        if is_starred is not None:
            sql += " AND i.is_starred = ?"
            params.append(1 if is_starred else 0)
        if is_read is not None:
            sql += " AND i.is_read = ?"
            params.append(1 if is_read else 0)
        if origin:
            sql += " AND i.origin = ?"
            params.append(origin)
        sql += " ORDER BY i.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cursor.execute(sql, params)
        db_rows = cursor.fetchall()

    rows = []
    for r in db_rows:
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
    cursor.execute("""
        SELECT i.*,
               (SELECT COUNT(*) FROM item_citations WHERE target_item_id = i.id) AS citations_count,
               (SELECT COUNT(*) FROM item_citations WHERE source_parent_id = i.id) AS sub_entities_count
        FROM items i
        WHERE i.id = ?
    """, (item_id,))
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
    allowed = {"is_read", "is_starred", "category_name", "title_l1", "summary_l1",
               "tech_tags", "deep_analysis", "content_raw", "cover_image", "origin"}
    if not updates or set(updates) - allowed:
        conn.close()
        raise ValueError("Unsupported item field")
    updates = {**updates, "updated_at": datetime.now(timezone.utc).isoformat()}
    fields = ", ".join(f"{k} = ?" for k in updates.keys())
    values = list(updates.values()) + [item_id]
    cursor.execute(f"UPDATE items SET {fields} WHERE id = ?", values)
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok

def delete_item(item_id: str) -> bool:
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM behavior_events WHERE item_id = ? OR proposal_id IN (SELECT id FROM proposals WHERE item_id = ?)", (item_id, item_id))
        conn.execute("DELETE FROM proposals WHERE item_id = ?", (item_id,))
        conn.execute("UPDATE watch_targets SET fingerprint_item_id = NULL, fingerprint_version = NULL WHERE fingerprint_item_id = ?", (item_id,))
        conn.execute("UPDATE ingest_tasks SET item_id = NULL WHERE item_id = ?", (item_id,))
        return conn.execute("DELETE FROM items WHERE id = ?", (item_id,)).rowcount > 0

def get_status_counts() -> Dict[str, int]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM items WHERE is_read = 0")
    inbox = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM items WHERE is_starred = 1")
    starred = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM items WHERE is_read = 1")
    archived = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM items")
    total = cursor.fetchone()[0]
    conn.close()
    return {"inbox": inbox, "starred": starred, "archived": archived, "total": total}

# ── Radar Sources & Recommender DAO ──────────────────────────

def get_all_radar_sources(only_active: bool = False) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if only_active:
        cursor.execute("SELECT * FROM radar_sources WHERE is_active = 1 ORDER BY created_at DESC")
    else:
        cursor.execute("SELECT * FROM radar_sources ORDER BY created_at DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for r in rows:
        try:
            r["hot_hours"] = json.loads(r.get("hot_hours") or "[]")
        except Exception:
            r["hot_hours"] = []
    return rows

def get_radar_source(source_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM radar_sources WHERE id = ?", (source_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["hot_hours"] = json.loads(d.get("hot_hours") or "[]")
    except Exception:
        d["hot_hours"] = []
    return d

def save_radar_source(data: Dict[str, Any]) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    source_id = data.get("id") or f"src_{uuid.uuid4().hex[:8]}"
    hot_hours_json = json.dumps(data.get("hot_hours") or [])
    cursor.execute("""
        INSERT INTO radar_sources (
            id, name, source_type, url, tier, hot_hours, check_interval_minutes, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            url = excluded.url,
            tier = excluded.tier,
            hot_hours = excluded.hot_hours,
            check_interval_minutes = excluded.check_interval_minutes,
            is_active = excluded.is_active
    """, (
        source_id,
        data["name"],
        data["source_type"],
        data["url"],
        data.get("tier", 2),
        hot_hours_json,
        data.get("check_interval_minutes", 60),
        data.get("is_active", 1)
    ))
    conn.commit()
    conn.close()
    return source_id

def delete_radar_source(source_id: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM radar_sources WHERE id = ?", (source_id,))
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return ok

def update_radar_source_fetch_meta(
    source_id: str,
    last_fetched_at: str,
    last_published_at: Optional[str] = None,
    etag: Optional[str] = None,
    last_modified_header: Optional[str] = None,
    hot_hours: Optional[List[int]] = None
):
    conn = get_db_connection()
    cursor = conn.cursor()
    updates = ["last_fetched_at = ?"]
    params = [last_fetched_at]
    if last_published_at:
        updates.append("last_published_at = ?")
        params.append(last_published_at)
    if etag is not None:
        updates.append("etag = ?")
        params.append(etag)
    if last_modified_header is not None:
        updates.append("last_modified_header = ?")
        params.append(last_modified_header)
    if hot_hours is not None:
        updates.append("hot_hours = ?")
        params.append(json.dumps(hot_hours))
    params.append(source_id)
    cursor.execute(f"UPDATE radar_sources SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()

# ── Topic Signal Tuning (Weights) ───────────────────────────

def get_all_topic_weights() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_topic_weights ORDER BY weight DESC, topic_tag ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_topic_weight(tag: str) -> float:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT weight, is_blocked, last_interacted_at FROM user_topic_weights WHERE topic_tag = ?", (tag.strip(),))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return 1.0
    if row["is_blocked"]:
        return -999.0
    from app.radar.recommender import calculate_time_decay
    return calculate_time_decay(float(row["weight"]), row["last_interacted_at"])

def tune_topic_signal(tag: str, action: str) -> Dict[str, Any]:
    if action not in ("boost", "dampen", "mute", "reset"):
        raise ValueError("Unsupported topic action")
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        return _tune_topic_signal(conn, tag, action)


def _tune_topic_signal(conn, tag: str, action: str) -> Dict[str, Any]:
    """
    Tune topic signal without tacky emojis:
    - action 'boost' (Tune Up): weight += 0.5, boost_count += 1
    - action 'dampen' (Tune Down): weight -= 1.0, dampen_count += 1
    - action 'mute' (Shield / Block): is_blocked = 1, weight = -10.0
    - action 'reset': weight = 1.0, is_blocked = 0
    """
    clean_tag = tag.strip()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_topic_weights WHERE topic_tag = ?", (clean_tag,))
    row = cursor.fetchone()
    now_iso = datetime.now(timezone.utc).isoformat()

    if not row:
        cur_weight = 1.0
        b_count = 0
        d_count = 0
        blocked = 0
    else:
        from app.radar.recommender import calculate_time_decay
        cur_weight = calculate_time_decay(float(row["weight"]), row["last_interacted_at"])
        b_count = int(row["boost_count"])
        d_count = int(row["dampen_count"])
        blocked = int(row["is_blocked"])

    if action == "boost":
        new_weight = min(10.0, cur_weight + 0.5)
        b_count += 1
        blocked = 0
    elif action == "dampen":
        new_weight = max(-5.0, cur_weight - 1.0)
        d_count += 1
    elif action == "mute":
        new_weight = -10.0
        blocked = 1
    elif action == "reset":
        new_weight = 1.0
        blocked = 0
    else:
        new_weight = cur_weight

    cursor.execute("""
        INSERT INTO user_topic_weights (
            topic_tag, weight, boost_count, dampen_count, is_blocked, last_interacted_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic_tag) DO UPDATE SET
            weight = excluded.weight,
            boost_count = excluded.boost_count,
            dampen_count = excluded.dampen_count,
            is_blocked = excluded.is_blocked,
            last_interacted_at = excluded.last_interacted_at
    """, (clean_tag, new_weight, b_count, d_count, blocked, now_iso))

    return {
        "topic_tag": clean_tag,
        "weight": new_weight,
        "boost_count": b_count,
        "dampen_count": d_count,
        "is_blocked": blocked,
        "last_interacted_at": now_iso
    }

# ── Radar Events & Digests ──────────────────────────────────

def save_radar_event(data: Dict[str, Any]) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    event_id = data.get("id") or f"evt_{uuid.uuid4().hex[:10]}"
    related_json = json.dumps(data.get("related_item_ids") or [])
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO radar_events (
            id, title, summary, primary_item_id, related_item_ids, unique_source_count, score, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            summary = excluded.summary,
            related_item_ids = excluded.related_item_ids,
            unique_source_count = excluded.unique_source_count,
            score = excluded.score,
            updated_at = excluded.updated_at
    """, (
        event_id,
        data["title"],
        data["summary"],
        data["primary_item_id"],
        related_json,
        data.get("unique_source_count", 1),
        data.get("score", 1.0),
        now_iso,
        now_iso
    ))
    conn.commit()
    conn.close()
    return event_id

def save_radar_digest(data: Dict[str, Any]) -> str:
    conn = get_db_connection()
    cursor = conn.cursor()
    digest_id = data.get("id") or f"dig_{uuid.uuid4().hex[:10]}"
    items_json = json.dumps(data.get("item_ids") or [])
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO radar_digests (
            id, title, digest_type, markdown_content, item_ids, created_at
        ) VALUES (?, ?, ?, ?, ?, ?)
    """, (
        digest_id,
        data["title"],
        data.get("digest_type", "evening"),
        data["markdown_content"],
        items_json,
        now_iso
    ))
    conn.commit()
    conn.close()
    return digest_id

def get_latest_radar_digests(limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM radar_digests ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for r in rows:
        try:
            r["item_ids"] = json.loads(r["item_ids"])
        except Exception:
            r["item_ids"] = []
    return rows

# ── Entity Fan-out & Citations DAO ──────────────────────────

def normalize_canonical_url(url: str) -> str:
    """Normalize project/repo URLs (strip trailing slashes, .git, fragments, params, lower-case host/repo)"""
    if not url:
        return ""
    clean = url.strip()
    # Strip URL fragments and query params
    if "#" in clean:
        clean = clean.split("#", 1)[0]
    if "?" in clean:
        clean = clean.split("?", 1)[0]
    clean = clean.rstrip("/")
    if clean.endswith(".git"):
        clean = clean[:-4]
    
    # Specific GitHub regex slug normalization: https://github.com/owner/repo
    m = re.match(r'^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)', clean, re.IGNORECASE)
    if m:
        owner = m.group(1).lower()
        repo = m.group(2).lower()
        return f"https://github.com/{owner}/{repo}"
    return clean

def find_item_by_canonical_or_url(url: str) -> Optional[Dict[str, Any]]:
    """Look up an existing item by canonical URL or matching git repo slug"""
    if not url:
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Exact match on raw url
    cursor.execute("SELECT * FROM items WHERE url = ? LIMIT 1", (url,))
    row = cursor.fetchone()
    if row:
        conn.close()
        d = dict(row)
        try:
            d["tech_tags"] = json.loads(d["tech_tags"])
        except Exception:
            d["tech_tags"] = []
        return d
    
    # 2. Canonical match
    canon = normalize_canonical_url(url)
    if canon:
        m = re.match(r'^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)', canon, re.IGNORECASE)
        if m:
            # Narrow SQL candidates but verify the exact normalized repo key.
            # Escaping LIKE metacharacters prevents '_' / '%' wildcard matches.
            slug = f"{m.group(1)}/{m.group(2)}"
            escaped = slug.replace("~", "~~").replace("%", "~%").replace("_", "~_")
            patterns = tuple(
                f"{scheme}://{host}/{escaped}%"
                for scheme in ("https", "http")
                for host in ("github.com", "www.github.com")
            )
            cursor.execute("""
                SELECT * FROM items
                WHERE lower(url) LIKE ? ESCAPE '~'
                   OR lower(url) LIKE ? ESCAPE '~'
                   OR lower(url) LIKE ? ESCAPE '~'
                   OR lower(url) LIKE ? ESCAPE '~'
            """, patterns)
            row = next(
                (candidate for candidate in cursor.fetchall()
                 if normalize_canonical_url(candidate["url"]) == canon),
                None,
            )
            if row:
                conn.close()
                d = dict(row)
                try:
                    d["tech_tags"] = json.loads(d["tech_tags"])
                except Exception:
                    d["tech_tags"] = []
                return d

        # Check if previously cited with this canonical URL
        cursor.execute("SELECT target_item_id FROM item_citations WHERE target_canonical_url = ? AND target_item_id IS NOT NULL LIMIT 1", (canon,))
        c_row = cursor.fetchone()
        if c_row and c_row["target_item_id"]:
            cursor.execute("SELECT * FROM items WHERE id = ? LIMIT 1", (c_row["target_item_id"],))
            row = cursor.fetchone()
            if row:
                conn.close()
                d = dict(row)
                try:
                    d["tech_tags"] = json.loads(d["tech_tags"])
                except Exception:
                    d["tech_tags"] = []
                return d
    
    conn.close()
    return None

def save_citation(data: Dict[str, Any]) -> str:
    """Save or update citation relationship between a parent digest and a child entity"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cit_id = data.get("id") or f"cit_{uuid.uuid4().hex[:10]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    
    parent_id = data["source_parent_id"]
    canon_url = normalize_canonical_url(data.get("target_canonical_url", ""))
    target_item_id = data.get("target_item_id")
    target_name = data.get("target_name") or ""
    context = data.get("mention_context") or ""

    # Check if this exact relationship already recorded
    cursor.execute("""
        SELECT id FROM item_citations 
        WHERE source_parent_id = ? AND (target_canonical_url = ? OR (target_item_id = ? AND target_item_id IS NOT NULL))
        LIMIT 1
    """, (parent_id, canon_url, target_item_id))
    existing = cursor.fetchone()

    if existing:
        cit_id = existing["id"]
        cursor.execute("""
            UPDATE item_citations 
            SET target_item_id = COALESCE(?, target_item_id),
                target_name = COALESCE(NULLIF(?, ''), target_name),
                mention_context = COALESCE(NULLIF(?, ''), mention_context)
            WHERE id = ?
        """, (target_item_id, target_name, context, cit_id))
    else:
        cursor.execute("""
            INSERT INTO item_citations (
                id, target_item_id, source_parent_id, target_canonical_url, target_name, mention_context, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (cit_id, target_item_id, parent_id, canon_url, target_name, context, now_iso))

    conn.commit()
    conn.close()
    return cit_id

def get_citations_for_target(target_item_id: str) -> List[Dict[str, Any]]:
    """Return all parent digests/videos that cited this target item"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id AS citation_id, c.mention_context, c.created_at AS cited_at,
               i.id AS parent_id, i.title_l1 AS parent_title, i.url AS parent_url, 
               i.source_type AS parent_source_type, i.cover_image AS parent_cover,
               i.author AS parent_author
        FROM item_citations c
        JOIN items i ON c.source_parent_id = i.id
        WHERE c.target_item_id = ?
        ORDER BY c.created_at DESC
    """, (target_item_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_sub_entities_for_parent(source_parent_id: str) -> List[Dict[str, Any]]:
    """Return all sub-projects cited/unpacked by this parent digest"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.id AS citation_id, c.target_item_id, c.target_canonical_url, c.target_name, c.mention_context,
               i.title_l1, i.summary_l1, i.tech_tags, i.category_name, i.cover_image, i.url AS item_url
        FROM item_citations c
        LEFT JOIN items i ON c.target_item_id = i.id
        WHERE c.source_parent_id = ?
        ORDER BY c.created_at ASC
    """, (source_parent_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    for r in rows:
        if r.get("tech_tags"):
            try:
                r["tech_tags"] = json.loads(r["tech_tags"])
            except Exception:
                r["tech_tags"] = []
        else:
            r["tech_tags"] = []
    return rows

# ── Ingest Tasks DAO (Hoarder Pattern / Persistent Queue) ──────

# Schema-preserving completion outbox: ingestion remains 'completed' while
# error_message stores a durable delivery cursor until the send succeeds.
# Delivery is at-least-once (a crash after remote success may resend).
_NOTIFY_PREFIX = "notify_v1:"
NOTIFICATION_PENDING = "notify_v1:pending:0"


def _parse_notification_state(value: Optional[str]):
    if not value or not value.startswith(_NOTIFY_PREFIX):
        return None
    parts = value.split(":", 4)
    if len(parts) < 3 or parts[1] not in {"pending", "inflight", "retry"}:
        return None
    try:
        attempts = int(parts[2])
        due = int(parts[3]) if parts[1] == "retry" and len(parts) > 3 else 0
    except ValueError:
        return None
    return parts[1], attempts, due


def claim_completion_notification(task_id: Optional[str] = None, now_epoch: Optional[int] = None):
    """Claim one due delivery with SQLite's write lock (never rerun the LLM)."""
    import time

    now_epoch = int(time.time()) if now_epoch is None else now_epoch
    conn = get_db_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        query = """
            SELECT * FROM ingest_tasks
            WHERE status = 'completed' AND error_message GLOB 'notify_v1:*'
        """
        params = ()
        if task_id:
            query += " AND id = ?"
            params = (task_id,)
        query += " ORDER BY updated_at ASC"
        for row in conn.execute(query, params).fetchall():
            state = _parse_notification_state(row["error_message"])
            if not state or state[0] == "inflight":
                continue
            if state[0] == "retry" and state[2] > now_epoch:
                continue
            marker = f"notify_v1:inflight:{state[1]}"
            updated = conn.execute("""
                UPDATE ingest_tasks SET error_message = ?, updated_at = ?
                WHERE id = ? AND status = 'completed' AND error_message = ?
            """, (marker, datetime.now(timezone.utc).isoformat(),
                  row["id"], row["error_message"]))
            if updated.rowcount:
                claimed = dict(row)
                claimed["error_message"] = marker
                conn.commit()
                return claimed
        conn.commit()
        return None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def finish_completion_notification(task_id: str, claim_marker: str, error: Optional[str] = None) -> bool:
    """Clear a successful delivery or persist a capped exponential retry."""
    import time

    state = _parse_notification_state(claim_marker)
    if not state or state[0] != "inflight":
        raise ValueError("Expected a claimed completion notification")
    next_marker = None
    if error is not None:
        attempts = state[1] + 1
        delay = min(30 * (2 ** min(attempts - 1, 7)), 3600)
        due = int(time.time()) + delay
        detail = str(error).replace("\n", " ").replace("\r", " ")[:160]
        next_marker = f"notify_v1:retry:{attempts}:{due}:{detail}"
    with closing(get_db_connection()) as conn, conn:
        updated = conn.execute("""
            UPDATE ingest_tasks SET error_message = ?, updated_at = ?
            WHERE id = ? AND status = 'completed' AND error_message = ?
        """, (next_marker, datetime.now(timezone.utc).isoformat(),
              task_id, claim_marker))
        return updated.rowcount > 0

def create_ingest_task(
    url: str,
    source: str = "telegram",
    chat_id: Optional[Any] = None,
    message_id: Optional[int] = None
) -> Dict[str, Any]:
    """Insert a new ingestion task into SQLite queue (fast, <10ms)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    task_id = uuid.uuid4().hex[:12]
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO ingest_tasks (id, url, source, chat_id, message_id, status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'queued', ?, ?)
    """, (task_id, url.strip(), source, chat_id, message_id, now_iso, now_iso))
    conn.commit()
    conn.close()
    return {
        "id": task_id,
        "url": url.strip(),
        "source": source,
        "chat_id": chat_id,
        "message_id": message_id,
        "status": "queued",
        "created_at": now_iso,
        "updated_at": now_iso
    }

def claim_next_task() -> Optional[Dict[str, Any]]:
    """Atomically fetch and lock the oldest queued task into 'processing' status"""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("""
            UPDATE ingest_tasks
            SET status = 'processing', updated_at = ?
            WHERE id = (
                SELECT id FROM ingest_tasks
                WHERE status = 'queued'
                ORDER BY created_at ASC
                LIMIT 1
            )
            RETURNING *
        """, (now_iso,))
        row = cursor.fetchone()
        conn.commit()
        if row:
            return dict(row)
        return None
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def update_task_status(
    task_id: str,
    status: str,
    item_id: Optional[str] = None,
    error_message: Optional[str] = None
) -> bool:
    """Update task lifecycle state (completed, failed, processing)"""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        UPDATE ingest_tasks
        SET status = ?,
            item_id = COALESCE(?, item_id),
            error_message = CASE
                WHEN ? = 'completed' AND (
                    (source = 'telegram' AND chat_id IS NOT NULL AND message_id IS NOT NULL)
                    OR (source = 'line' AND chat_id IS NOT NULL)
                ) THEN ?
                ELSE ?
            END,
            updated_at = ?
        WHERE id = ?
    """, (status, item_id, status, NOTIFICATION_PENDING,
          error_message, now_iso, task_id))
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def get_ingest_task(task_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve task by id"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ingest_tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def reset_stale_tasks(exclusive_owner: bool = False) -> int:
    """Recover interrupted work only while no other process owns this DB queue."""
    if not exclusive_owner:
        from app.file_lock import FileLock
        ownership = FileLock(settings.DATABASE_PATH + ".worker.lock")
        if not ownership.acquire():
            return 0
        try:
            return reset_stale_tasks(exclusive_owner=True)
        finally:
            ownership.release()
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        UPDATE ingest_tasks
        SET status = 'queued',
            retry_count = retry_count + 1,
            updated_at = ?
        WHERE status = 'processing'
    """, (now_iso,))
    count = cursor.rowcount
    # A crash during delivery must restore only the notification, never
    # the completed ingestion or its LLM retry counter.
    cursor.execute("""
        UPDATE ingest_tasks
        SET error_message = replace(error_message, 'notify_v1:inflight:', 'notify_v1:pending:'),
            updated_at = ?
        WHERE status = 'completed' AND error_message GLOB 'notify_v1:inflight:*'
    """, (now_iso,))
    conn.commit()
    conn.close()
    return count

# ── User Settings DAO (Heartbeat / Quiet A/B Mode) ──────────────

def get_user_setting(user_id: Any, default_mode: str = "heartbeat") -> str:
    """Retrieve interaction mode ('heartbeat' or 'quiet') for a given user/chat"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT interaction_mode FROM user_settings WHERE user_id = ?", (str(user_id),))
    row = cursor.fetchone()
    conn.close()
    if row and row["interaction_mode"]:
        return row["interaction_mode"]
    return default_mode

def set_user_setting(user_id: Any, interaction_mode: str) -> bool:
    """Save or update interaction mode preference"""
    mode = interaction_mode.lower().strip()
    if mode not in ("heartbeat", "quiet"):
        mode = "heartbeat"
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO user_settings (user_id, interaction_mode, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            interaction_mode = excluded.interaction_mode,
            updated_at = excluded.updated_at
    """, (str(user_id), mode, now_iso, now_iso))
    conn.commit()
    conn.close()
    return True


# ── Interest Profile DAO (A-minimal: profile-in-prompt) ───────────

MAX_PROFILE_CHARS = 2000

def get_interest_profile_record() -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT profile_text, updated_at FROM user_interest_profile WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {"profile": "", "updated_at": None}
    return {"profile": row["profile_text"] or "", "updated_at": row["updated_at"]}

def get_interest_profile() -> str:
    return get_interest_profile_record()["profile"]

def set_interest_profile(text: str) -> bool:
    clean = (text or "").strip()[:MAX_PROFILE_CHARS]
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO user_interest_profile (id, profile_text, updated_at)
        VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            profile_text = excluded.profile_text,
            updated_at = excluded.updated_at
    """, (clean, now_iso))
    conn.commit()
    conn.close()
    return True

def get_pending_analysis_items(limit: int = 10) -> List[Dict[str, Any]]:
    """Radar stubs saved past the analysis cap, oldest first (backfill queue)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM items
        WHERE origin = 'radar' AND analysis_status = 'pending'
        ORDER BY created_at ASC LIMIT ?
    """, (limit,))
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


# ── Dream Pass (Taste Self-Reflection) DAO ──────────────────────

def create_dreampass_proposal(observations: str, suggested_profile: str, diff_summary: str, current_profile: str = "") -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO profile_dreampass_proposals
        (status, observations, suggested_profile, diff_summary, current_profile, created_at)
        VALUES ('pending', ?, ?, ?, ?, ?)
    """, (observations.strip(), suggested_profile.strip(), diff_summary.strip(), current_profile.strip(), now_iso))
    conn.commit()
    prop_id = cursor.lastrowid
    conn.close()
    return prop_id

def get_latest_dreampass_proposal(status: Optional[str] = None) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute("SELECT * FROM profile_dreampass_proposals WHERE status = ? ORDER BY id DESC LIMIT 1", (status,))
    else:
        cursor.execute("SELECT * FROM profile_dreampass_proposals ORDER BY id DESC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_dreampass_proposal(proposal_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM profile_dreampass_proposals WHERE id = ?", (proposal_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def apply_dreampass_proposal(proposal_id: int) -> bool:
    prop = get_dreampass_proposal(proposal_id)
    if not prop or prop["status"] != "pending":
        return False
    # Update interest profile
    set_interest_profile(prop["suggested_profile"])
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE profile_dreampass_proposals
        SET status = 'applied', applied_at = ?
        WHERE id = ?
    """, (now_iso, proposal_id))
    conn.commit()
    conn.close()
    return True

def dismiss_dreampass_proposal(proposal_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE profile_dreampass_proposals
        SET status = 'dismissed'
        WHERE id = ? AND status = 'pending'
    """, (proposal_id,))
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def get_recent_taste_signals(days: int = 7) -> Dict[str, Any]:
    """Aggregates interactions (stars, boosts, dampens, reads) and positive/negative items."""
    conn = get_db_connection()
    cursor = conn.cursor()
    # 1. Behavior counts
    cursor.execute("""
        SELECT event_type, COUNT(*) AS c FROM behavior_events
        WHERE julianday(created_at) > julianday('now', ?)
        GROUP BY event_type
    """, (f"-{days} days",))
    event_counts = {r["event_type"]: r["c"] for r in cursor.fetchall()}

    # 2. Positively engaged items (starred or boosted)
    cursor.execute("""
        SELECT DISTINCT i.id, i.title_l1, i.summary_l1, i.tech_tags, i.category_name, i.source_type
        FROM items i
        LEFT JOIN behavior_events b ON b.item_id = i.id
        WHERE (i.is_starred = 1 OR b.event_type IN ('swipe_star', 'boost', 'open_snapshot'))
          AND julianday(i.created_at) > julianday('now', ?)
        ORDER BY i.created_at DESC LIMIT 20
    """, (f"-{days} days",))
    positive_items = []
    for r in cursor.fetchall():
        d = dict(r)
        try:
            d["tech_tags"] = json.loads(d["tech_tags"]) if d["tech_tags"] else []
        except Exception:
            d["tech_tags"] = []
        positive_items.append(d)

    # 3. Negatively engaged items (dampened or muted)
    cursor.execute("""
        SELECT DISTINCT i.id, i.title_l1, i.tech_tags, b.event_type
        FROM behavior_events b
        JOIN items i ON b.item_id = i.id
        WHERE b.event_type IN ('dampen', 'mute', 'swipe_down')
          AND julianday(b.created_at) > julianday('now', ?)
        ORDER BY b.created_at DESC LIMIT 15
    """, (f"-{days} days",))
    negative_items = []
    for r in cursor.fetchall():
        d = dict(r)
        try:
            d["tech_tags"] = json.loads(d["tech_tags"]) if d["tech_tags"] else []
        except Exception:
            d["tech_tags"] = []
        negative_items.append(d)

    # 4. Top radar topic weights
    cursor.execute("SELECT topic_tag, weight FROM user_topic_weights WHERE is_blocked = 0 ORDER BY weight DESC LIMIT 10")
    top_topics = [{"tag": r["topic_tag"], "weight": r["weight"]} for r in cursor.fetchall()]

    conn.close()
    return {
        "event_counts": event_counts,
        "positive_items": positive_items,
        "negative_items": negative_items,
        "top_topics": top_topics,
        "window_days": days,
    }


# ── Hard Rules Engine DAO ───────────────────────────────────────

def create_rule(name: str, field: str, operator: str, value: str,
                action_type: str, action_value: str = "",
                priority: int = 10, is_active: int = 1) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO rules (name, field, operator, value, action_type, action_value, priority, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (name.strip(), field.strip().lower(), operator.strip().lower(), value.strip(),
          action_type.strip().lower(), (action_value or "").strip(), priority, is_active, now_iso, now_iso))
    conn.commit()
    rule_id = cursor.lastrowid
    conn.close()
    return rule_id

def get_all_rules(active_only: bool = False) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if active_only:
        cursor.execute("SELECT * FROM rules WHERE is_active = 1 ORDER BY priority ASC, id ASC")
    else:
        cursor.execute("SELECT * FROM rules ORDER BY priority ASC, id ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_rule(rule_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def update_rule(rule_id: int, updates: Dict[str, Any]) -> bool:
    allowed = {"name", "is_active", "priority", "field", "operator", "value", "action_type", "action_value"}
    clean_updates = {k: v for k, v in updates.items() if k in allowed}
    if not clean_updates:
        return False
    clean_updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    set_clause = ", ".join(f"{k} = ?" for k in clean_updates)
    params = list(clean_updates.values()) + [rule_id]
    cursor.execute(f"UPDATE rules SET {set_clause} WHERE id = ?", params)
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def delete_rule(rule_id: int) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed




# ── Watch Targets DAO (Local Proposal Engine) ────────────────────

WATCH_READ_KEYS = ["filenames", "readme", "deps", "code", "git"]
WATCH_OUTBOUND_KEYS = ["summary", "docs", "deps", "code", "git"]

WATCH_PRESETS = {
    "open": {
        "read": {k: True for k in WATCH_READ_KEYS},
        "outbound": {k: True for k in WATCH_OUTBOUND_KEYS},
    },
    "balanced": {
        "read": {"filenames": True, "readme": True, "deps": True, "code": False, "git": False},
        "outbound": {"summary": True, "docs": True, "deps": True, "code": False, "git": False},
    },
    "strict": {
        "read": {"filenames": True, "readme": True, "deps": False, "code": False, "git": False},
        "outbound": {"summary": True, "docs": False, "deps": False, "code": False, "git": False},
    },
}

def _normalize_toggle_map(raw: Any, keys: List[str]) -> Dict[str, bool]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except (ValueError, TypeError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {k: bool(raw.get(k, False)) for k in keys}

def _target_row_to_dict(row: Any) -> Dict[str, Any]:
    d = dict(row)
    d["read_scope"] = _normalize_toggle_map(d.get("read_scope"), WATCH_READ_KEYS)
    d["outbound_consent"] = _normalize_toggle_map(d.get("outbound_consent"), WATCH_OUTBOUND_KEYS)
    d["is_active"] = bool(d.get("is_active"))
    return d

def add_watch_target(name: str, path: str, target_type: str = "folder",
                     preset: str = "balanced", read_scope: Optional[Dict] = None,
                     outbound_consent: Optional[Dict] = None) -> Dict[str, Any]:
    tid = uuid.uuid4().hex[:12]
    if preset in WATCH_PRESETS and read_scope is None and outbound_consent is None:
        p = WATCH_PRESETS[preset]
        read_scope, outbound_consent = p["read"], p["outbound"]
    read_scope = _normalize_toggle_map(read_scope or {}, WATCH_READ_KEYS)
    outbound_consent = _normalize_toggle_map(outbound_consent or {}, WATCH_OUTBOUND_KEYS)
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    cursor.execute("""
        INSERT INTO watch_targets (id, name, target_type, path, preset, read_scope,
                                   outbound_consent, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
    """, (tid, name.strip(), target_type, str(path), preset,
          json.dumps(read_scope), json.dumps(outbound_consent), now_iso, now_iso))
    conn.commit()
    conn.close()
    return {"id": tid, "name": name.strip(), "path": str(path), "target_type": target_type,
            "preset": preset, "read_scope": read_scope, "outbound_consent": outbound_consent,
            "is_active": True}

def get_watch_targets(active_only: bool = False) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    q = "SELECT * FROM watch_targets"
    if active_only:
        q += " WHERE is_active = 1"
    q += " ORDER BY created_at ASC"
    cursor.execute(q)
    rows = [_target_row_to_dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def get_watch_target(target_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM watch_targets WHERE id = ?", (target_id,))
    row = cursor.fetchone()
    conn.close()
    return _target_row_to_dict(row) if row else None

def update_watch_target(target_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    updates = dict(updates)
    if "read_scope" in updates:
        updates["read_scope"] = json.dumps(_normalize_toggle_map(updates["read_scope"], WATCH_READ_KEYS))
    if "outbound_consent" in updates:
        updates["outbound_consent"] = json.dumps(_normalize_toggle_map(updates["outbound_consent"], WATCH_OUTBOUND_KEYS))
    if "is_active" in updates:
        updates["is_active"] = 1 if updates["is_active"] else 0
    allowed = {"name", "path", "target_type", "preset", "read_scope", "outbound_consent",
               "is_active", "last_scan_at", "fingerprint_item_id", "fingerprint_version"}
    fields = {key: value for key, value in updates.items() if key in allowed}
    if fields:
        with closing(get_db_connection()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            fingerprint = fields.get("fingerprint_item_id")
            if fingerprint and not conn.execute("SELECT 1 FROM items WHERE id = ?", (fingerprint,)).fetchone():
                raise ValueError("Unknown fingerprint item")
            fields["updated_at"] = datetime.now(timezone.utc).isoformat()
            sets = ", ".join(f"{key} = ?" for key in fields)
            conn.execute(f"UPDATE watch_targets SET {sets} WHERE id = ?", [*fields.values(), target_id])
    return get_watch_target(target_id)


def delete_watch_target(target_id: str) -> bool:
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        # Preserve existing proposal cards and decisions, detach the removed target.
        conn.execute("UPDATE proposals SET target_id = NULL WHERE target_id = ?", (target_id,))
        return conn.execute("DELETE FROM watch_targets WHERE id = ?", (target_id,)).rowcount > 0

# ── Proposals DAO (glass-box suggestion cards) ───────────────────

def proposal_seen(dedup_key: str, conn=None) -> bool:
    if conn is None:
        with closing(get_db_connection()) as owned:
            return proposal_seen(dedup_key, owned)
    return conn.execute("""
        SELECT 1 FROM proposals WHERE dedup_key = ?
        AND julianday(created_at) > julianday('now', '-30 days') LIMIT 1
    """, (dedup_key,)).fetchone() is not None


def save_proposal(proposal: Dict[str, Any], item_data=None) -> Optional[Dict[str, Any]]:
    """Atomically deduplicate and save both the card and proposal, without a migration."""
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if proposal.get("dedup_key") and proposal_seen(proposal["dedup_key"], conn):
            return None
        target_id = proposal.get("target_id")
        if target_id and not conn.execute("SELECT 1 FROM watch_targets WHERE id = ?", (target_id,)).fetchone():
            raise ValueError("Unknown proposal target")
        item_id = _save_item(conn, item_data) if item_data is not None else proposal["item_id"]
        if not conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
            raise ValueError("Unknown proposal item")
        pid = uuid.uuid4().hex[:12]
        conn.execute("""
            INSERT INTO proposals (id, item_id, target_id, proposal_type, impact, confidence,
                                   effort, status, dedup_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
        """, (pid, item_id, target_id, proposal.get("proposal_type", "risk"),
              float(proposal.get("impact", 5)), float(proposal.get("confidence", 5)),
              float(proposal.get("effort", 5)), proposal.get("dedup_key"), datetime.now(timezone.utc).isoformat()))
        return dict(conn.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone())


def get_proposal(proposal_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_proposals(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    if status:
        cursor.execute(
            "SELECT * FROM proposals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit))
    else:
        cursor.execute("SELECT * FROM proposals ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

def decide_proposal(proposal_id: str, status: str,
                    corrections: Optional[Dict[str, float]] = None,
                    reason: str = "") -> Optional[Dict[str, Any]]:
    if status not in ("approved", "dismissed"):
        return None
    conn = get_db_connection()
    cursor = conn.cursor()
    sets = ["status = ?", "decided_at = ?"]
    vals: list = [status, datetime.now(timezone.utc).isoformat()]
    if corrections:
        for k in ("impact", "confidence", "effort"):
            if k in corrections and corrections[k] is not None:
                sets.append(f"user_{k} = ?")
                vals.append(float(corrections[k]))
    if reason:
        sets.append("correction_reason = ?")
        vals.append(reason)
    vals.append(proposal_id)
    cursor.execute(f"UPDATE proposals SET {', '.join(sets)} WHERE id = ?", vals)
    conn.commit()
    ok = cursor.rowcount > 0
    conn.close()
    return get_proposal(proposal_id) if ok else None

# ── Backup Runs DAO ──────────────────────────────────────────────

def log_backup_run(sink: str, status: str, file_path: str = "",
                   size_bytes: int = 0, error: str = "") -> Dict[str, Any]:
    rid = uuid.uuid4().hex[:12]
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO backup_runs (id, sink, status, file_path, size_bytes, error, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (rid, sink, status, file_path, int(size_bytes), error,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return {"id": rid, "sink": sink, "status": status, "file_path": file_path,
            "size_bytes": size_bytes, "error": error}

def get_backup_runs(limit: int = 10) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM backup_runs ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

# ── Behavior Events DAO (P1 swipe/click/view fuel) ───────────────
# Design rule: swipe_up/down/star are TRAINING LABELS; snooze ("稍後")
# re-queues only and must NEVER be used as a training label.

SWIPE_LABEL_EVENTS = ("swipe_up", "swipe_down", "swipe_star")

def record_swipe(event_type: str, item_id: str, source: str = "api", meta=None):
    """Exactly one training decision per item; label, weights and item state commit together."""
    if event_type not in (*SWIPE_LABEL_EVENTS, "snooze"):
        raise ValueError("Unsupported swipe event")
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        item = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if not item:
            raise ValueError("Unknown item")
        prior = conn.execute("SELECT id, event_type FROM behavior_events WHERE item_id = ? AND event_type IN ('swipe_up','swipe_down','swipe_star') LIMIT 1", (item_id,)).fetchone()
        if prior:
            return {**dict(prior), "duplicate": True}
        now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute("INSERT INTO behavior_events (event_type, item_id, source, meta, created_at) VALUES (?, ?, ?, ?, ?)", (event_type, item_id, source, json.dumps(meta or {}, ensure_ascii=False), now))
        if event_type in SWIPE_LABEL_EVENTS:
            try:
                tags = json.loads(item["tech_tags"] or "[]")
            except (ValueError, TypeError):
                tags = []
            for tag in dict.fromkeys(str(tag).strip() for tag in (tags if isinstance(tags, list) else []) if str(tag).strip()):
                _tune_topic_signal(conn, str(tag), "dampen" if event_type == "swipe_down" else "boost")
            conn.execute("UPDATE items SET is_read = 1, is_starred = CASE WHEN ? = 'swipe_star' THEN 1 WHEN ? = 'swipe_down' THEN 0 ELSE is_starred END, updated_at = ? WHERE id = ?", (event_type, event_type, now, item_id))
        return {"id": cursor.lastrowid, "event_type": event_type, "duplicate": False}

def log_behavior_event(event_type: str, item_id: Optional[str] = None,
                       proposal_id: Optional[str] = None, source: str = "api",
                       meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with closing(get_db_connection()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if item_id and not conn.execute("SELECT 1 FROM items WHERE id = ?", (item_id,)).fetchone():
            raise ValueError("Unknown item")
        if proposal_id:
            proposal = conn.execute("SELECT item_id FROM proposals WHERE id = ?", (proposal_id,)).fetchone()
            if not proposal or (item_id and proposal["item_id"] != item_id):
                raise ValueError("Unknown or mismatched proposal")
        cursor = conn.execute("""
            INSERT INTO behavior_events (event_type, item_id, proposal_id, source, meta, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (event_type, item_id, proposal_id, source,
              json.dumps(meta or {}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
        return {"id": cursor.lastrowid, "event_type": event_type}


def get_behavior_stats(days: int = 7) -> Dict[str, Any]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT event_type, COUNT(*) AS count FROM behavior_events
        WHERE julianday(created_at) > julianday('now', ?)
        GROUP BY event_type ORDER BY count DESC
    """, (f"-{days} days",))
    by_type = {r["event_type"]: r["count"] for r in cursor.fetchall()}
    cursor.execute("SELECT COUNT(*) AS c FROM behavior_events")
    total = cursor.fetchone()["c"]
    conn.close()
    return {"total_events": total, "window_days": days, "by_type": by_type}

def get_swipe_deck(limit: int = 10) -> List[Dict[str, Any]]:
    """Un-acted radar items, newest first.

    Exclusions: any swipe label ever (decided cards don't return), and
    snoozed cards within the last day (稍後 = re-queue, not a label).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT i.* FROM items i
        WHERE i.origin = 'radar' AND i.is_read = 0
          AND i.analysis_status != 'pending'
          AND NOT EXISTS (
              SELECT 1 FROM behavior_events e
              WHERE e.item_id = i.id AND e.event_type IN ('swipe_up','swipe_down','swipe_star'))
          AND NOT EXISTS (
              SELECT 1 FROM behavior_events e
              WHERE e.item_id = i.id AND e.event_type = 'snooze'
                AND julianday(e.created_at) > julianday('now', '-1 day'))
        ORDER BY i.created_at DESC
    """)
    rows = []
    for r in cursor.fetchall():
        d = dict(r)
        try:
            d["tech_tags"] = json.loads(d["tech_tags"])
        except Exception:
            d["tech_tags"] = []
        rows.append(d)
    conn.close()
    from app.watch.taste import rank_deck
    return rank_deck(rows)[:limit]
