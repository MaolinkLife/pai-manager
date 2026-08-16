# ===========================================================
# Module: hf_routes.py
# Purpose: HuggingFace hub import — search, file listing, managed downloads
# Used in: /settings → Models (HF import section)
# ========================================================

from fastapi import APIRouter, Header, HTTPException, Query

from modules.hf_hub import service as hf_service

router = APIRouter(prefix="/api/hf", tags=["HuggingFace"])


@router.get("/search")
async def search_models(q: str = Query(..., min_length=2), limit: int = Query(20, ge=1, le=50)):
    return await hf_service.search_models(q, limit=limit)


@router.get("/files")
async def list_repo_files(
    repo: str = Query(..., min_length=3),
    x_hf_token: str | None = Header(default=None, alias="X-HF-Token"),
):
    return await hf_service.list_repo_files(repo, token=x_hf_token)


@router.get("/downloads")
async def get_downloads():
    return hf_service.snapshot()


@router.post("/download")
async def start_download(payload: dict):
    repo = str(payload.get("repo") or "").strip()
    path = str(payload.get("path") or "").strip()
    category = str(payload.get("category") or "").strip()
    if not repo or not path or not category:
        raise HTTPException(status_code=400, detail="repo, path and category are required")
    result = hf_service.start_download(
        repo, path, category, token=str(payload.get("token") or "") or None
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.post("/download/cancel")
async def cancel_download(payload: dict):
    key = str(payload.get("id") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="id is required")
    return hf_service.cancel_download(key)
