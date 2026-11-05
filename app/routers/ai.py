"""設定 › AI 服務商: provider cards, connections, task slots and connection tests.

Keys are write-only: responses carry key_configured and the last four
characters (key_hint), never the key. Every route sits behind the API key gate.
"""
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import ai_connections, ai_status, provider_catalog
from app.ai_connections import AIConfigError
from app.connection_checks import check_connection

router = APIRouter(prefix="/api/ai", tags=["AI providers"])


class ConnectionBody(BaseModel):
    card: Optional[str] = None
    label: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    key: Optional[str] = None  # None or left out: keep the saved key; "": remove it
    caps: Optional[Dict[str, Any]] = None
    min_interval: Optional[float] = None
    max_concurrency: Optional[int] = None
    enabled: Optional[bool] = None
    slot: Optional[str] = None  # create only: also append to this slot


class SlotsBody(BaseModel):
    slots: Dict[str, List[Any]] = Field(default_factory=dict)


class TestBody(BaseModel):
    """Unsaved values typed in the form; fields left out use the saved connection."""
    card: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    key: Optional[str] = None
    purpose: str = "chat"  # chat | embeddings


def _error(exc: AIConfigError) -> JSONResponse:
    first = next(iter(exc.errors.values()), "設定有誤")
    return JSONResponse(status_code=400, content={"detail": first, "errors": exc.errors})


def _given(body: BaseModel) -> Dict[str, Any]:
    return {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "slot"}


def _overview() -> Dict[str, Any]:
    return {
        "connections": [ai_connections.describe_connection(c) for c in ai_connections.list_connections()],
        **ai_connections.describe_slots(),
        "needs_setup": ai_connections.needs_setup(),
    }


@router.get("/catalog")
async def get_catalog():
    return provider_catalog.catalog()


@router.get("/connections")
async def list_connections():
    return _overview()


@router.post("/connections", status_code=201)
async def create_connection(body: ConnectionBody):
    try:
        conn = ai_connections.create(_given(body), slot=body.slot)
    except AIConfigError as exc:
        return _error(exc)
    return {"connection": ai_connections.describe_connection(conn), **_overview()}


@router.patch("/connections/{connection_id}")
async def update_connection(connection_id: int, body: ConnectionBody):
    try:
        conn = ai_connections.update(connection_id, _given(body))
    except KeyError:
        raise HTTPException(404, "找不到這條連線")
    except AIConfigError as exc:
        return _error(exc)
    return {"connection": ai_connections.describe_connection(conn), **_overview()}


@router.delete("/connections/{connection_id}")
async def delete_connection(connection_id: int):
    if not ai_connections.delete(connection_id):
        raise HTTPException(404, "找不到這條連線")
    return _overview()


def _draft(saved: Optional[ai_connections.Connection], body: TestBody) -> Any:
    """What to test: the saved connection with the typed fields laid over it."""
    card_id = body.card or (saved.card if saved else None)
    card = provider_catalog.card(card_id or "")
    if card is None:
        raise AIConfigError({"card": "不是可用的服務商卡片"})
    kind = saved.kind if saved and not body.card else card["kind"]
    base_url = (body.base_url if body.base_url is not None else (saved.base_url if saved else card["base_url"])).strip()
    key = body.key if body.key is not None else (saved.key if saved else "")
    if saved and body.key is None and saved.key and base_url.rstrip("/") != saved.base_url.rstrip("/"):
        raise AIConfigError({"key": "更換 API 位址時，請一併輸入要測試的 API 金鑰"})
    if saved and body.key is None and saved.key_broken:
        raise AIConfigError({"key": "這把金鑰無法解密（主金鑰不同），請重新輸入"})
    if "<" in base_url:
        raise AIConfigError({"base_url": "把位址裡角括號的部分（例如 <帳號 ID>）換成你自己的值"})
    if card["key_mode"] == "required" and not (key or "").strip():
        raise AIConfigError({"key": "請輸入 API 金鑰"})
    model = (body.model if body.model is not None else (saved.model if saved else card["model"])).strip()
    if not model:
        raise AIConfigError({"model": "請填模型名稱"})
    caps = dict(card.get("caps", {}))
    caps.update(saved.caps if saved else {})
    if body.purpose == "embeddings" and body.model is None:
        # The vector test uses the embedding model, not the chat model.
        model = str(caps.get("embedding_model") or card.get("embedding_model") or model)
    return SimpleNamespace(kind=kind, base_url=base_url, key=(key or "").strip(), model=model, caps=caps)


@router.post("/test")
async def test_unsaved(body: TestBody):
    """Test values typed in the wizard or a new-connection form, before saving anything."""
    try:
        draft = _draft(None, body)
    except AIConfigError as exc:
        return {"ok": False, "status": None, "message": next(iter(exc.errors.values())), "detail": ""}
    return await check_connection(draft, purpose=body.purpose)


@router.post("/connections/{connection_id}/test")
async def test_connection(connection_id: int, body: Optional[TestBody] = None,
                          slot_model: Optional[str] = Query(None, alias="model")):
    saved = ai_connections.get_connection(connection_id)
    if saved is None:
        raise HTTPException(404, "找不到這條連線")
    body = body or TestBody()
    try:
        draft = _draft(saved, body)
    except AIConfigError as exc:
        return {"ok": False, "status": None, "message": next(iter(exc.errors.values())), "detail": ""}
    result = await check_connection(draft, model=slot_model, purpose=body.purpose)
    untouched = body.base_url is None and body.key is None and body.model is None and body.card is None
    if untouched:
        # The status light follows a test of what is saved; a passing test also lifts
        # "needs a person" and the cooldown.
        if result["ok"]:
            ai_status.record_success(saved.status_key, saved.label)
            if body.purpose == "chat" and result.get("json_mode") is False and saved.caps.get("json_mode", True):
                ai_connections.update(connection_id, {"caps": {**saved.caps, "json_mode": False}})
        else:
            ai_status.record_failure(saved.status_key, result.get("status"),
                                     result.get("detail") or result.get("message", ""), saved.label)
    return result


@router.get("/slots")
async def get_slots():
    return ai_connections.describe_slots()


@router.put("/slots")
async def put_slots(body: SlotsBody):
    before = ai_connections.slots()
    try:
        ai_connections.set_slots(body.slots)
    except AIConfigError as exc:
        return _error(exc)
    after = ai_connections.slots()
    first = lambda entries: (entries[0]["connection_id"], entries[0]["model"]) if entries else None  # noqa: E731
    reindex = "embeddings" in body.slots and first(before["embeddings"]) != first(after["embeddings"])
    return {**_overview(), "reindex_hint": reindex}
