import re
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from app.database import get_db_connection, save_radar_event

def _extract_keywords(text: str) -> set:
    words = re.findall(r"[\w\u4e00-\u9fff]{2,}", text.lower())
    # remove common stop words
    stopwords = {"https", "http", "github", "release", "releases", "update", "v1", "v2", "com", "www"}
    return {w for w in words if w not in stopwords}

def cluster_item_to_event(item: Dict[str, Any]) -> str:
    """
    Groups the item into an existing event if related within the last 48 hours,
    or creates a new event.
    Returns: event_id
    """
    item_id = item["id"]
    title = item.get("title_l1") or item.get("title", "")
    summary = item.get("summary_l1") or item.get("content", "")
    tags = set(item.get("tech_tags") or [])
    item_keywords = _extract_keywords(title)

    conn = get_db_connection()
    cursor = conn.cursor()
    # Fetch events in the last 48 hours
    cursor.execute("""
        SELECT * FROM radar_events 
        WHERE datetime(created_at) >= datetime('now', '-2 days')
        ORDER BY updated_at DESC
    """)
    recent_events = [dict(r) for r in cursor.fetchall()]
    conn.close()

    best_match_event = None
    highest_overlap = 0.0

    for evt in recent_events:
        evt_title = evt["title"]
        evt_keywords = _extract_keywords(evt_title)
        
        intersection = item_keywords & evt_keywords
        union = item_keywords | evt_keywords
        jaccard = len(intersection) / len(union) if union else 0.0

        if jaccard > 0.35 and jaccard > highest_overlap:
            highest_overlap = jaccard
            best_match_event = evt

    if best_match_event:
        # Merge into existing event
        event_id = best_match_event["id"]
        try:
            related_ids = json.loads(best_match_event.get("related_item_ids") or "[]")
        except Exception:
            related_ids = []

        if item_id not in related_ids and item_id != best_match_event["primary_item_id"]:
            related_ids.append(item_id)

        unique_sources = best_match_event.get("unique_source_count", 1) + 1
        new_score = round(best_match_event.get("score", 1.0) + 1.0, 2)

        save_radar_event({
            "id": event_id,
            "title": best_match_event["title"],
            "summary": best_match_event["summary"],
            "primary_item_id": best_match_event["primary_item_id"],
            "related_item_ids": related_ids,
            "unique_source_count": unique_sources,
            "score": new_score
        })
        return event_id
    else:
        # Create new primary event
        event_id = save_radar_event({
            "title": title,
            "summary": summary[:200],
            "primary_item_id": item_id,
            "related_item_ids": [],
            "unique_source_count": 1,
            "score": 1.0
        })
        return event_id
