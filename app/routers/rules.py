from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from app.database import (
    create_rule,
    get_all_rules,
    get_rule,
    update_rule,
    delete_rule,
)
from app.rules import evaluate_rules_for_preview

router = APIRouter(prefix="/api/rules", tags=["Hard Rules Engine"])


class RuleCreateRequest(BaseModel):
    name: str = Field(..., description="規則名稱，如：GitHub 倉庫自動歸檔")
    field: str = Field(..., description="比對欄位：url, domain, title, source_type, content")
    operator: str = Field(..., description="比對運算子：contains, equals, startswith, endswith, regex")
    value: str = Field(..., description="比對值或正規表達式")
    action_type: str = Field(..., description="執行動作：add_tag, set_category, star, archive, mute")
    action_value: Optional[str] = Field("", description="動作參數（標籤名或分類名）")
    priority: Optional[int] = Field(10, description="優先權（數字越小越優先執行）")
    is_active: Optional[int] = Field(1, description="是否啟用（1: 啟用, 0: 停用）")


class RuleUpdateRequest(BaseModel):
    name: Optional[str] = None
    field: Optional[str] = None
    operator: Optional[str] = None
    value: Optional[str] = None
    action_type: Optional[str] = None
    action_value: Optional[str] = None
    priority: Optional[int] = None
    is_active: Optional[int] = None


class RuleTestRequest(BaseModel):
    url: Optional[str] = ""
    title: Optional[str] = ""
    source_type: Optional[str] = "web"
    category_name: Optional[str] = "Inbox"
    tech_tags: Optional[List[str]] = []
    content: Optional[str] = ""


@router.get("", response_model=List[Dict[str, Any]])
async def list_rules(active_only: bool = Query(False, description="僅回傳啟用的規則")):
    """List all hard automation rules."""
    return get_all_rules(active_only=active_only)


@router.post("", response_model=Dict[str, Any])
async def add_rule(payload: RuleCreateRequest):
    """Create a new hard automation rule."""
    valid_fields = {"url", "domain", "title", "source_type", "content"}
    valid_operators = {"contains", "equals", "startswith", "endswith", "regex"}
    valid_actions = {"add_tag", "set_category", "star", "archive", "mute"}

    if payload.field.lower() not in valid_fields:
        raise HTTPException(status_code=400, detail=f"Invalid field. Must be one of {valid_fields}")
    if payload.operator.lower() not in valid_operators:
        raise HTTPException(status_code=400, detail=f"Invalid operator. Must be one of {valid_operators}")
    if payload.action_type.lower() not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action_type. Must be one of {valid_actions}")

    rule_id = create_rule(
        name=payload.name,
        field=payload.field,
        operator=payload.operator,
        value=payload.value,
        action_type=payload.action_type,
        action_value=payload.action_value or "",
        priority=payload.priority if payload.priority is not None else 10,
        is_active=payload.is_active if payload.is_active is not None else 1,
    )
    rule = get_rule(rule_id)
    return {"success": True, "rule": rule}


@router.get("/{rule_id}", response_model=Dict[str, Any])
async def fetch_rule(rule_id: int):
    """Fetch single rule by ID."""
    rule = get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch("/{rule_id}", response_model=Dict[str, Any])
async def modify_rule(rule_id: int, payload: RuleUpdateRequest):
    """Update rule properties or toggle active state."""
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    ok = update_rule(rule_id, updates)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule = get_rule(rule_id)
    return {"success": True, "rule": rule}


@router.delete("/{rule_id}", response_model=Dict[str, Any])
async def remove_rule(rule_id: int):
    """Delete a rule by ID."""
    ok = delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"success": True, "message": "Rule deleted"}


@router.post("/test", response_model=Dict[str, Any])
async def test_rule_evaluation(payload: RuleTestRequest):
    """Test rule evaluation on simulated item fields and preview actions taken."""
    item = payload.model_dump()
    return evaluate_rules_for_preview(item)
