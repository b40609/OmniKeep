from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

from app.brain import ask_brain, get_brain_status

router = APIRouter(prefix="/api/brain", tags=["Ask Brain"])


class ChatMessage(BaseModel):
    role: str
    content: str


class AskBrainRequest(BaseModel):
    question: str
    history: Optional[List[ChatMessage]] = None
    limit: Optional[int] = 5
    force_cloud: Optional[bool] = False


@router.post("/ask")
async def ask_endpoint(req: AskBrainRequest):
    if not req.question or not req.question.strip():
        raise HTTPException(status_code=400, detail="問題內容不能為空")

    history_dicts = None
    if req.history:
        history_dicts = [{"role": m.role, "content": m.content} for m in req.history]

    res = await ask_brain(
        question=req.question.strip(),
        history=history_dicts,
        limit=req.limit or 5,
        force_cloud=req.force_cloud or False,
    )
    return res


@router.get("/status")
async def status_endpoint():
    return get_brain_status()
