"""HTTP surface for §3.9-quinquies user reminders.

Reminders are usually captured in-chat by the decision layer; this REST
surface backs the features/tasks UI: list, manual create, edit, cancel.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from modules.reminders import reminders_repository
from modules.system import character as character_service
from modules.system.service import get_active_character_name

router = APIRouter(prefix="/api/reminders", tags=["Reminders"])


class ReminderCreateBody(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    due_at: str  # ISO-8601; naive values are treated as UTC
    channel: str = "main_chat"


class ReminderUpdateBody(BaseModel):
    text: Optional[str] = Field(default=None, max_length=500)
    due_at: Optional[str] = None


def _parse_due(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _active_character_id() -> str:
    char_name = get_active_character_name(default="default_waifu")
    character = character_service.get_or_create_character(char_name)
    return character.id


@router.get("/")
def list_reminders(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    try:
        result = reminders_repository.list(
            character_id=_active_character_id(),
            status=status,
            limit=limit,
            offset=offset,
        )
        return {"status": "success", **result}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/")
def create_reminder(body: ReminderCreateBody):
    due = _parse_due(body.due_at)
    if due is None:
        return JSONResponse(status_code=422, content={"error": "invalid due_at"})
    if due <= datetime.now(timezone.utc):
        return JSONResponse(status_code=422, content={"error": "due_at must be in the future"})
    try:
        row = reminders_repository.create(
            character_id=_active_character_id(),
            text=body.text,
            due_at=due,
            channel=body.channel or "main_chat",
            source="api",
        )
        return {"status": "success", "reminder": row}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.patch("/{reminder_id}")
def update_reminder(reminder_id: str, body: ReminderUpdateBody):
    due = None
    if body.due_at is not None:
        due = _parse_due(body.due_at)
        if due is None:
            return JSONResponse(status_code=422, content={"error": "invalid due_at"})
    try:
        row = reminders_repository.update(reminder_id, text=body.text, due_at=due)
        if row is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return {"status": "success", "reminder": row}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/{reminder_id}/cancel")
def cancel_reminder(reminder_id: str):
    try:
        row = reminders_repository.mark(reminder_id, status="cancelled")
        if row is None:
            return JSONResponse(status_code=404, content={"error": "not found"})
        return {"status": "success", "reminder": row}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
