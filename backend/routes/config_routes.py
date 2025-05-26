from fastapi import APIRouter, Request
from config import config_loader

router = APIRouter(prefix="/api/config", tags=["Config"])


# Возвращает весь конфиг
@router.get("/")
def get_full_config():
    return config_loader.get_config()


# Перезаписывает конфиг целиком.
@router.post("/")
async def overwrite_config(request: Request):
    new_config = await request.json()
    config_loader.save_config(new_config)
    return {"status": "ok", "message": "Конфиг обновлён."}


# Обновляет отдельный путь ("api.model", "voice.language", и т.п.)
@router.patch("/")
async def update_config_value(payload: dict):
    """
    {
        "path": "api.model",
        "value": "qwen3:14b"
    }
    """
    path = payload.get("path")
    value = payload.get("value")
    if not path:
        return {"status": "error", "message": "Отсутствует путь."}

    config_loader.set_config_value(path, value)
    return {"status": "ok", "message": f"Значение '{path}' обновлено."}
