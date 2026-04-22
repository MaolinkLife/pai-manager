from fastapi import APIRouter
from fastapi.responses import JSONResponse
from modules.system.logger import get_debug_log

router = APIRouter(prefix="/api/log", tags=["Logs"])


@router.get("/")
def get_current_session_log(limit: int | None = None, offset: int = 0, session_id: str | None = None):
    try:
        logs, resolved_session_id, total = get_debug_log(limit=limit, offset=offset, session_id=session_id)
        if logs is None:
            return JSONResponse(
                status_code=404, content={"error": "Log file not found"}
            )

        safe_offset = max(int(offset or 0), 0)
        page_size = len(logs)
        has_more = (safe_offset + page_size) < int(total or 0)
        return {
            "session_id": resolved_session_id,
            "logs": logs,
            "total": int(total or 0),
            "offset": safe_offset,
            "limit": limit,
            "has_more": has_more,
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Error processing request", "details": str(e)},
        )
