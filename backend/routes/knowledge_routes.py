# ===========================================================
# Module: knowledge_routes.py
# Purpose: Knowledge collections — document indexing over the vector store
# Used in: /library (collections UI), decision layer retrieval
# ========================================================

import asyncio

from fastapi import APIRouter, HTTPException, Query

from modules.documents import service as documents_service

router = APIRouter(prefix="/api/knowledge", tags=["Knowledge"])


@router.get("/collections")
async def list_collections():
    return {"status": "ok", "collections": documents_service.list_collections()}


@router.post("/collections")
async def create_collection(payload: dict):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    collection = documents_service.create_collection(
        name, str(payload.get("description") or "")
    )
    return {"status": "ok", "collection": collection}


@router.patch("/collections/{collection_id}")
async def update_collection(collection_id: str, payload: dict):
    collection = documents_service.update_collection(
        collection_id,
        name=payload.get("name"),
        description=payload.get("description"),
        enabled=payload.get("enabled"),
    )
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"status": "ok", "collection": collection}


@router.delete("/collections/{collection_id}")
async def delete_collection(collection_id: str):
    if not documents_service.delete_collection(collection_id):
        raise HTTPException(status_code=404, detail="Collection not found")
    return {"status": "ok"}


@router.get("/collections/{collection_id}/files")
async def list_files(collection_id: str):
    return {"status": "ok", "files": documents_service.list_files(collection_id)}


@router.post("/collections/{collection_id}/files")
async def add_file(collection_id: str, payload: dict):
    media_id = str(payload.get("media_id") or "").strip()
    if not media_id:
        raise HTTPException(status_code=400, detail="media_id is required")
    try:
        # Indexing embeds every chunk — keep the event loop responsive.
        file = await asyncio.to_thread(
            documents_service.add_file_from_library, collection_id, media_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "file": file}


@router.post("/files/{file_id}/reindex")
async def reindex_file(file_id: str):
    try:
        file = await asyncio.to_thread(documents_service.index_file, file_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "ok", "file": file}


@router.delete("/files/{file_id}")
async def remove_file(file_id: str):
    if not documents_service.remove_file(file_id):
        raise HTTPException(status_code=404, detail="File not found")
    return {"status": "ok"}


@router.post("/collections/{collection_id}/reindex")
async def reindex_collection(collection_id: str):
    files = await asyncio.to_thread(documents_service.reindex_collection, collection_id)
    return {"status": "ok", "files": files}


@router.get("/search")
async def search(q: str = Query(..., min_length=2), top_k: int = Query(0, ge=0, le=20)):
    matches = await asyncio.to_thread(
        documents_service.search, q, top_k=top_k or None
    )
    return {"status": "ok", "matches": matches}
