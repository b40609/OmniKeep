from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.database import (
    get_items,
    get_item_by_id,
    update_item_field,
    delete_item,
    get_status_counts,
    get_citations_for_target,
    get_sub_entities_for_parent
)

router = APIRouter(prefix="/api/items", tags=["Items"])

class ItemUpdate(BaseModel):
    category_name: Optional[str] = None
    is_starred: Optional[int] = None
    is_read: Optional[int] = None
    title_l1: Optional[str] = None
    summary_l1: Optional[str] = None

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
