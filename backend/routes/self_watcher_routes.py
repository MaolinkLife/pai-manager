"""HTTP surface for Self-Watcher (§3.7) expectation events.

Read-only: the table is written by the per-turn check inside the
generation pipeline; the nightly reflection consumes it. This endpoint
lets the UI (diary / future timeline view) inspect raw mismatches.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from modules.self_watcher.repository import self_watcher_repository
from modules.system import character as character_service
from modules.system.service import get_active_character_name

router = APIRouter(prefix="/api/self_watcher", tags=["SelfWatcher"])


@router.get("/events")
def list_events(
    character_id: str | None = Query(default=None),
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=500),
):
    try:
        resolved_character_id = (character_id or "").strip()
        if not resolved_character_id:
            char_name = get_active_character_name(default="default")
            character = character_service.get_or_create_character(char_name)
            resolved_character_id = getattr(character, "id", "") or ""

        events = self_watcher_repository.list_recent(
            character_id=resolved_character_id,
            lookback_days=days,
            limit=limit,
        )
        return {
            "events": events,
            "total": len(events),
            "days": days,
            "character_id": resolved_character_id,
        }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": "list failed", "details": str(exc)},
        )
