# =========================================================
# Модуль: config_routes.py
# Назначение: Эндпоинты API для работы с конфигурацией LIM
# Используется в: WebUI и любых внешних компонентах, которым нужно читать/менять config
# Особенности:
# - Поддерживает полную замену и частичное обновление
# - Возвращает весь конфиг через GET-запрос
# =========================================================

from fastapi import APIRouter, Request

from services.config_service import (
    update_config_bulk, 
    save_config, 
    apply_preset_by_name, 
    get_config
)

router = APIRouter(prefix="/api/config", tags=["Config"])


# Возвращает весь конфиг
@router.get("/")
def get_full_config():
    return get_config()


# Перезаписывает конфиг целиком.
@router.post("/")
async def overwrite_config(request: Request):
    new_config = await request.json()
    save_config(new_config)
    return {"status": "ok", "message": "Конфиг обновлён."}


# Обновляет config 
@router.patch("/")
async def update_config_bulk_route(request: Request):
    updates = await request.json()
    updated, failed = update_config_bulk(updates)

    return {
        "status": "partial" if failed else "ok",
        "updated": updated,
        "failed": failed
    }
    
# Применяет выбранный пресет
@router.post("/apply_preset")
async def apply_preset(request: Request):
    body = await request.json()
    preset_name = body.get("name")

    if not preset_name:
        return {"status": "error", "message": "Название пресета не указано"}

    success = apply_preset_by_name(preset_name)
    if success:
        return {"status": "ok", "message": f"Пресет '{preset_name}' применён."}
    else:
        return {"status": "error", "message": "Пресет не найден"}