from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from modules.storage.service import (
    delete_library_item,
    get_media_entry,
    list_library_items,
    read_library_text,
    resolve_media_path,
    save_library_file,
)

router = APIRouter(prefix="/api/media", tags=["Media"])


@router.get("/library")
def get_library(
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    q: str = "",
    category: str = "",
):
    return list_library_items(limit=limit, offset=offset, query=q, category=category)


@router.post("/library")
async def upload_library_file(
    file: UploadFile = File(...),
    description: str | None = Form(default=None),
):
    file_bytes = await file.read()
    item = save_library_file(
        file_name=file.filename or "file",
        mime_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
        description=description,
    )
    return {"status": "ok", "item": item}


@router.get("/library/{media_id}/content")
def get_library_text_content(media_id: str):
    return read_library_text(media_id)


@router.delete("/library/{media_id}")
def delete_library_media(media_id: str):
    return delete_library_item(media_id)


@router.get("/{media_id}")
def download_media(media_id: str):
    entry = get_media_entry(media_id)
    file_path = resolve_media_path(entry)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        media_type=entry.mime_type,
        filename=entry.file_name,
    )
