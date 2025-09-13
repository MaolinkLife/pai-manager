# routes/resources_routes.py (обновлённый)
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from services.logger_service import get_debug_log
from services.resource_service import get_audio_resources
from services.monitor_service import (
    get_monitor_screens,
    get_monitor_info,
)  # Добавляем импорт

router = APIRouter(prefix="/api/resources", tags=["Resources"])


@router.get("/devices")
def get_audio_devices():
    try:
        return get_audio_resources()

    except Exception as e:
        return {
            "status": "error",
            "content": f"Error while getting audio devices: {str(e)}",
        }


# НОВЫЙ ENDPOINT - Получение скриншотов мониторов
@router.get("/monitors/screens")
def get_monitor_screens_endpoint():
    """
    Получить список мониторов с превьюшками для выбора в UI
    """
    try:
        monitors = get_monitor_screens()
        return {"status": "success", "monitors": monitors}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting monitor screens: {str(e)}",
            "monitors": [],
        }


# Дополнительный endpoint для получения информации о мониторах
@router.get("/monitors/info")
def get_monitor_info_endpoint():
    """
    Получить информацию о мониторах без превьюшек
    """
    try:
        info = get_monitor_info()
        return {"status": "success", "data": info}
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error getting monitor info: {str(e)}",
            "data": {},
        }
