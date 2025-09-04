from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services import api_service, ollama_service
# from services.history_service import get_history
from services import config_service, database_service
from services.logger_service import log_audit_entry, AuditStatus
from services.lorebook_service import get_lore_by_keyword

router = APIRouter(prefix="/api/lorebook", tags=["Lorebook"])

@router.get("/")
def get_lorebook_entries(keyword: str = Query(...)):
    entries = get_lore_by_keyword(keyword, limit=5)
    return {"result": entries}