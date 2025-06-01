from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services.logger_service import get_debug_log
from services.resource_service import get_audio_resources

router = APIRouter(prefix="/api/resources", tags=["Resources"])


@router.get("/devices")
def get_audio_devices():
    try:
        return get_audio_resources()
    
    except Exception as e:
        return {
            "status": "error",
            "content": f"Ошибка при получении аудиоустройств: {str(e)}"
        }
