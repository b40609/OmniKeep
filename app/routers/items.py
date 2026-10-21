from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.database import get_items, get_item_by_id, update_item_field, delete_item

router = APIRouter(prefix="/api/items", tags=["Items"])

class ItemUpdate(BaseModel):
    category_name: Optional[str] = None
    is_starred: Optional[int] = None
    is_read: Optional[int] = None
    title_l1: Optional[str] = None
    summary_l1: Optional[str] = None

@router.get("", response_model=List[Dict[str, Any]])
async def list_items(
    category: Optional[str] = Query(None, description="Category filter"),
    q: Optional[str] = Query(None, description="Full-text search query"),
    starred: Optional[bool] = Query(None, description="Filter starred items only"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0)
):
    return get_items(category=category, query=q, is_starred=starred, limit=limit, offset=offset)

@router.get("/{item_id}")
async def get_item(item_id: str):
    item = get_item_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
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
