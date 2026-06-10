"""HTTP surface for DebugVault.

Minimal CRUD for the UI:
  GET  /api/debug_vault            — paginated list with filters
  GET  /api/debug_vault/{id}       — single entry detail
  POST /api/debug_vault/{id}/review — mark reviewed (optional note in body)
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from modules.debug_vault.repository import debug_vault_repository


router = APIRouter(prefix="/api/debug_vault", tags=["DebugVault"])


@router.get("/")
def list_entries(
    kind: Optional[str] = None,
    reviewed: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
):
    try:
        payload = debug_vault_repository.list(
            kind=kind,
            reviewed=reviewed,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": "list failed", "details": str(exc)},
        )

    return {
        "entries": payload["rows"],
        "total": payload["total"],
        "limit": limit,
        "offset": offset,
        "has_more": (offset + len(payload["rows"])) < payload["total"],
    }


@router.get("/{entry_id}")
def get_entry(entry_id: str):
    entry = debug_vault_repository.get(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="vault entry not found")
    return entry


@router.post("/{entry_id}/review")
def mark_reviewed(entry_id: str, payload: dict | None = None):
    note = None
    if isinstance(payload, dict):
        note = payload.get("note")
    ok = debug_vault_repository.mark_reviewed(entry_id, note=note)
    if not ok:
        raise HTTPException(status_code=404, detail="vault entry not found")
    return {"id": entry_id, "reviewed": True}
