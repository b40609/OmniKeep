from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any
from app.database import get_all_categories, add_category, delete_category

router = APIRouter(prefix="/api/categories", tags=["Categories"])

class CategoryCreate(BaseModel):
    name: str
    icon: str = "tag"

@router.get("", response_model=List[Dict[str, Any]])
async def list_categories():
    return get_all_categories()

@router.post("", response_model=Dict[str, Any])
async def create_category(payload: CategoryCreate):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name cannot be empty")
    res = add_category(name, payload.icon)
    if not res:
        raise HTTPException(status_code=409, detail=f"Category '{name}' already exists")
    return res

@router.delete("/{name}")
async def remove_category(name: str):
    ok = delete_category(name)
    if not ok:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"success": True, "message": f"Category '{name}' removed, items moved to Inbox"}
