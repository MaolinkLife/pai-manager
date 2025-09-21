# api/lorebook_routes.py
# ==========================================================
# Module: lorebook_routes.py
# Purpose: FastAPI endpoints for Lorebook management
# Used: by WebUI for knowledge base management
# ==========================================================

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from services.lorebook_service import (
    get_lorebook_entries,
    add_lorebook_entry,
    update_lorebook_entry,
    delete_lorebook_entry,
)

router = APIRouter(prefix="/api/lorebook", tags=["Lorebook"])


@router.get("/", response_model=List[Dict[str, Any]])
def get_all_entries():
    """Получить все записи из Lorebook"""
    return get_lorebook_entries()


@router.post("/", response_model=Dict[str, Any])
def create_entry(entry: Dict[str, Any]):
    """Создать новую запись в Lorebook"""
    if add_lorebook_entry(entry):
        return {"status": "success", "entry": entry}
    else:
        raise HTTPException(status_code=500, detail="Failed to create entry")


@router.put("/{entry_id}", response_model=Dict[str, Any])
def update_entry(entry_id: int, entry: Dict[str, Any]):
    """Обновить запись в Lorebook"""
    if update_lorebook_entry(entry_id, entry):
        return {"status": "success", "entry": entry}
    else:
        raise HTTPException(status_code=404, detail="Entry not found")


@router.delete("/{entry_id}")
def delete_entry(entry_id: int):
    """Удалить запись из Lorebook"""
    if delete_lorebook_entry(entry_id):
        return {"status": "success", "message": "Entry deleted"}
    else:
        raise HTTPException(status_code=404, detail="Entry not found")


@router.get("/search")
def search_entries(query: str = ""):
    """Поиск записей по ключевым словам"""
    entries = get_lorebook_entries()
    if not query:
        return entries

    query = query.lower()
    filtered_entries = []
    for entry in entries:
        content = entry.get("content", "").lower()
        keywords = entry.get("keywords", "").lower()
        category = entry.get("category", "").lower()

        if query in content or query in keywords or query in category:
            filtered_entries.append(entry)

    return filtered_entries
