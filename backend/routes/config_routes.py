# =========================================================
# Модуль: config_routes.py
# Назначение: Эндпоинты API для работы с конфигурацией LIM
# Используется в: WebUI и любых внешних компонентах, которым нужно читать/менять config
# Особенности:
# - Поддерживает полную замену и частичное обновление
# - Возвращает весь конфиг через GET-запрос
# =========================================================

from fastapi import APIRouter, Request

from services import config_service
from services.config_service import update_config_bulk

router = APIRouter(prefix="/api/config", tags=["Config"])


# Возвращает весь конфиг
@router.get("/")
def get_full_config():
    return config_service.get_config()


# Перезаписывает конфиг целиком.
@router.post("/")
async def overwrite_config(request: Request):
    new_config = await request.json()
    config_service.save_config(new_config)
    return {"status": "ok", "message": "Конфиг обновлён."}


# Обновляет config 
@router.patch("/")
async def update_config_bulk_route(request: Request):
    updates = await request.json()
    updated, failed = config_service.update_config_bulk(updates)

    return {
        "status": "partial" if failed else "ok",
        "updated": updated,
        "failed": failed
    }