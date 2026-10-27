from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
import io
import json
import zipfile
import re
from datetime import datetime
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.database import (
    get_items,
    get_item_by_id,
    update_item_field,
    delete_item,
    get_status_counts,
    get_citations_for_target,
    get_sub_entities_for_parent,
    seed_demo_items
)

router = APIRouter(prefix="/api/items", tags=["Items"])

class ItemUpdate(BaseModel):
    category_name: Optional[str] = None
    is_starred: Optional[int] = None
    is_read: Optional[int] = None
    title_l1: Optional[str] = None
    summary_l1: Optional[str] = None

@router.post("/seed-demo")
async def seed_demo():
    items = seed_demo_items()
    return {
        "success": True,
        "count": len(items),
        "message": f"已成功注入 {len(items)} 個示範項目"
    }


@router.get("/stats", response_model=Dict[str, int])
async def get_stats():
    return get_status_counts()

@router.get("/search/semantic")
async def search_semantic(
    q: str = Query(..., description="Semantic search query"),
    limit: int = Query(10, ge=1, le=50)
):
    from app.vector import search_hybrid
    return search_hybrid(q, limit=limit)

@router.get("", response_model=List[Dict[str, Any]])
async def list_items(
    category: Optional[str] = Query(None, description="Category filter"),
    q: Optional[str] = Query(None, description="Full-text search query"),
    starred: Optional[bool] = Query(None, description="Filter starred items only"),
    read: Optional[bool] = Query(None, description="Filter read status (False for unread/Inbox, True for archived)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    return get_items(category=category, query=q, is_starred=starred, is_read=read, limit=limit, offset=offset)

@router.get("/export")
async def export_items(
    format: str = Query("json", description="Export format: json or markdown (zip)"),
    starred_only: bool = Query(False, description="Export only starred items"),
    category: Optional[str] = Query(None, description="Filter by category")
):
    items = get_items(
        category=category,
        is_starred=True if starred_only else None,
        limit=100000,
        offset=0
    )
    now_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    if format.lower() == "json":
        data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "count": len(items),
            "items": items
        }
        json_bytes = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return Response(
            content=json_bytes,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="omnikeep_export_{now_str}.json"'
            }
        )
    elif format.lower() in ("markdown", "zip", "md"):
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for item in items:
                title = item.get("title_l1") or "untitled"
                safe_title = re.sub(r'[\/:*?"<>|]', "_", title)[:60].strip()
                date_prefix = (item.get("created_at") or "")[:10] or "nodate"
                filename = f"{date_prefix}_{safe_title}.md"

                tags_list = item.get("tech_tags") or "[]"
                if isinstance(tags_list, str):
                    try:
                        tags_list = json.loads(tags_list)
                    except Exception:
                        tags_list = [t.strip() for t in tags_list.split(",") if t.strip()]
                tags_yaml = ", ".join([f'"{t}"' for t in tags_list])

                md_content = f"""---
title: "{title.replace('"', '\"')}"
url: "{item.get('url', '')}"
category: "{item.get('category_name', 'Inbox')}"
tags: [{tags_yaml}]
starred: {str(bool(item.get('is_starred'))).lower()}
read: {str(bool(item.get('is_read'))).lower()}
created_at: "{item.get('created_at', '')}"
---

# {title}

> **核心摘要與痛點**  
> {item.get('summary_l1', '')}

## 深度技術架構解構 (Architecture Details)
{item.get('deep_analysis') or '（無深入分析）'}

---
## 原文收錄內容 (Raw Content)
{item.get('content_raw') or '（無原文內容）'}
"""
                zf.writestr(filename, md_content.encode("utf-8"))

        zip_buf.seek(0)
        return StreamingResponse(
            zip_buf,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="omnikeep_markdown_{now_str}.zip"'
            }
        )
    else:
        raise HTTPException(status_code=400, detail="Unsupported export format. Use 'json' or 'markdown'")


@router.get("/{item_id}/snapshot")
async def get_snapshot(item_id: str):
    from app.snapshot import get_html_snapshot
    content = get_html_snapshot(item_id)
    if not content:
        raise HTTPException(status_code=404, detail="No HTML snapshot available for this item")
    return HTMLResponse(content=content, media_type="text/html; charset=utf-8")

@router.get("/{item_id}/snapshot/status")
async def get_snapshot_status(item_id: str):
    from app.snapshot import get_snapshot_info
    return get_snapshot_info(item_id)

@router.get("/{item_id}")
async def get_item(item_id: str):
    item = get_item_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # Enrich with citations (which digests cited this item) & sub_entities (items/projects packed inside this digest)
    item["citations"] = get_citations_for_target(item_id)
    item["sub_entities"] = get_sub_entities_for_parent(item_id)
    return item

@router.patch("/{item_id}")
async def update_item(item_id: str, payload: ItemUpdate):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    ok = update_item_field(item_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"success": True, "item_id": item_id}

@router.delete("/{item_id}")
async def remove_item(item_id: str):
    ok = delete_item(item_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"success": True, "message": "Item deleted"}


@router.post("/import/bookmarks")
async def import_bookmarks_endpoint(request: Request):
    """Import bookmarks from Netscape HTML, Chrome/Pocket JSON, or CSV."""
    content_type = request.headers.get("content-type", "")
    content = ""
    filename = ""
    enqueue_ai = False
    default_category = "Inbox"

    if "multipart/form-data" in content_type:
        form = await request.form()
        uploaded_file = form.get("file")
        if uploaded_file and hasattr(uploaded_file, "read"):
            content_bytes = await uploaded_file.read()
            content = content_bytes.decode("utf-8", errors="replace")
            filename = getattr(uploaded_file, "filename", "") or ""
        else:
            content = str(form.get("content") or form.get("raw_content") or "")

        enqueue_ai = str(form.get("enqueue_ai", "")).lower() in ("true", "1", "yes")
        default_category = str(form.get("default_category") or "Inbox")
    else:
        try:
            body = await request.json()
        except Exception:
            body = {}
        content = body.get("content") or ""
        filename = body.get("filename") or ""
        enqueue_ai = bool(body.get("enqueue_ai", False))
        default_category = body.get("default_category") or "Inbox"

    if not content.strip():
        raise HTTPException(status_code=400, detail="請提供書籤檔案內容 (Bookmark content or file is required)")

    from app.parsers.bookmarks import parse_bookmarks
    from app.network import is_safe_url
    from app.database import save_item, create_ingest_task
    from app.rules import apply_rules_to_item

    parsed_items = parse_bookmarks(content, filename=filename)
    if not parsed_items:
        return {
            "success": True,
            "total_parsed": 0,
            "imported_count": 0,
            "queued_count": 0,
            "skipped_count": 0,
            "errors": [],
            "sample_ids": [],
        }

    imported_count = 0
    queued_count = 0
    skipped_count = 0
    errors: List[str] = []
    saved_ids: List[str] = []

    for item in parsed_items:
        url = item.get("url", "").strip()
        if not url or not is_safe_url(url):
            skipped_count += 1
            continue

        if enqueue_ai:
            try:
                task = create_ingest_task(url=url, source="import")
                queued_count += 1
                saved_ids.append(task["id"])
            except Exception as e:
                errors.append(f"{url}: {str(e)}")
                skipped_count += 1
        else:
            try:
                item_rec = {
                    "url": url,
                    "source_type": "web",
                    "category_name": default_category,
                    "title_l1": item.get("title") or url,
                    "summary_l1": f"自書籤匯入（分類/資料夾：{item.get('folder', 'Bookmarks')}）",
                    "tech_tags": item.get("tags") or [],
                    "deep_analysis": "",
                    "origin": "import",
                }
                item_rec = apply_rules_to_item(item_rec)
                item_id = save_item(item_rec)
                imported_count += 1
                saved_ids.append(item_id)
            except Exception as e:
                errors.append(f"{url}: {str(e)}")
                skipped_count += 1

    return {
        "success": True,
        "total_parsed": len(parsed_items),
        "imported_count": imported_count,
        "queued_count": queued_count,
        "skipped_count": skipped_count,
        "errors": errors[:10],
        "sample_ids": saved_ids[:10],
    }
