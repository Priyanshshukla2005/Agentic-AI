"""Phase 6 API: the launch checklist (stored on the server).

GET    /api/checklist/{session_id}            -> items + progress {done, total, percent}
PATCH  /api/checklist/{session_id}/{item_id}  {done: bool}       -> tick / untick
POST   /api/checklist/{session_id}            {title, detail?}   -> add your own step
DELETE /api/checklist/{session_id}/{item_id}                     -> own steps only (403 for plan steps)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import checklist
from app.checklist import ChecklistItem, Progress
from app.session_store import get_session

router = APIRouter(prefix="/api/checklist", tags=["checklist"])


class ChecklistResponse(BaseModel):
    items: list[ChecklistItem]
    progress: Progress


class DoneRequest(BaseModel):
    done: bool


class NewItemRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, examples=["Buy a weighing scale"])
    detail: str = Field("", max_length=1000)


def ensure_session(session_id: str) -> None:
    if get_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")


def full_response(session_id: str) -> dict:
    items = checklist.list_items(session_id)
    return {"items": items, "progress": checklist.progress(items)}


@router.get("/{session_id}", response_model=ChecklistResponse)
def get_checklist(session_id: str):
    """All steps (plan steps first, then your own) and how many are done."""
    ensure_session(session_id)
    return full_response(session_id)


@router.patch("/{session_id}/{item_id}", response_model=ChecklistResponse)
def tick(session_id: str, item_id: int, body: DoneRequest):
    ensure_session(session_id)
    if checklist.set_done(session_id, item_id, body.done) is None:
        raise HTTPException(status_code=404, detail=f"Checklist item {item_id} not found.")
    return full_response(session_id)


@router.post("/{session_id}", response_model=ChecklistResponse, status_code=201)
def add_step(session_id: str, body: NewItemRequest):
    ensure_session(session_id)
    if not body.title.strip():
        raise HTTPException(status_code=400, detail="Title must not be empty.")
    checklist.add_custom(session_id, body.title, body.detail)
    return full_response(session_id)


@router.delete("/{session_id}/{item_id}", response_model=ChecklistResponse)
def delete_step(session_id: str, item_id: int):
    ensure_session(session_id)
    result = checklist.delete_item(session_id, item_id)
    if result == "not_found":
        raise HTTPException(status_code=404, detail=f"Checklist item {item_id} not found.")
    if result == "forbidden":
        raise HTTPException(status_code=403, detail="Steps from the plan cannot be deleted; tick them when done.")
    return full_response(session_id)
