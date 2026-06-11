# ===========================================================
# Module: update_routes.py
# Purpose: Self-update — check GitHub for a newer version and fast-forward
# Used in: system-settings («Обновления» section)
# ========================================================

import asyncio

from fastapi import APIRouter

from modules.system import updater

router = APIRouter(prefix="/api/system/update", tags=["Update"])


@router.get("/check")
async def check_update():
    # git fetch + two GitHub requests — keep the event loop responsive.
    return await asyncio.to_thread(updater.check_update)


@router.post("/run")
async def run_update(payload: dict | None = None):
    target = str((payload or {}).get("target") or "branch")
    if target not in {"branch", "release"}:
        target = "branch"
    return await asyncio.to_thread(updater.run_update, target)
