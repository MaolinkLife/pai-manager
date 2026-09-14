"""The model index: what each model can do; the owner's marks. Owner only."""

import asyncio
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel

from core.interaction import resolve_actor_uuid_from_auth_header, resolve_interaction_policy
from modules.model_index import service as model_index

router = APIRouter(prefix="/api/models/index", tags=["Model index"])


def _require_owner(request: Request) -> str:
    actor_uuid = resolve_actor_uuid_from_auth_header(request.headers.get("authorization"))
    if resolve_interaction_policy(actor_uuid).actor_role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can do this")
    return actor_uuid


@router.get("")
async def get_model_index(
    request: Request,
    provider: str = Query(default=model_index.OLLAMA),
    capability: Optional[str] = Query(default=None),
):
    """The index, brought in line with what Ollama has installed first."""
    _require_owner(request)
    sync = None
    if provider == model_index.OLLAMA:
        sync = await asyncio.to_thread(model_index.sync_ollama)
    entries = await asyncio.to_thread(model_index.list_entries, provider, capability)
    return {"status": "ok", "sync": sync, "models": entries}


class OwnerCapabilitiesRequest(BaseModel):
    provider: str = model_index.OLLAMA
    name: str
    capabilities: Optional[List[str]] = None


@router.put("/capabilities")
async def set_model_capabilities(payload: OwnerCapabilitiesRequest, request: Request):
    """The owner's marks; `capabilities: null` goes back to what the metadata declares."""
    _require_owner(request)
    try:
        entry = await asyncio.to_thread(
            model_index.set_owner_capabilities, payload.provider, payload.name, payload.capabilities
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {"status": "ok", "model": entry}
