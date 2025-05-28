from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from services import preset_service

router = APIRouter(prefix="/api/presets", tags=["Presets"])


# 📦 Получить список всех пресетов
@router.get("/")
def get_presets():
    try:
        presets = preset_service.get_all_presets()
        return {"status": "ok", "presets": presets}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# 🎯 Получить пресет по имени
@router.get("/{name}")
def get_preset(name: str):
    preset = preset_service.get_preset_by_name(name)
    if preset:
        return {"status": "ok", "preset": preset}
    return JSONResponse(status_code=404, content={"status": "error", "message": "Пресет не найден"})


# 💾 Добавить или обновить пресет
@router.post("/")
async def save_preset(request: Request):
    try:
        preset = await request.json()
        if not preset.get("name"):
            return JSONResponse(status_code=400, content={"status": "error", "message": "Имя пресета обязательно"})

        preset_service.update_or_add_preset(preset)
        return {"status": "ok", "message": "Пресет сохранён"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


@router.post("/apply")
async def apply_existing_preset(request: Request):
    try:
        data = await request.json()
        preset_name = data.get("name")

        if not preset_name:
            return JSONResponse(status_code=400, content={"status": "error", "message": "Preset name is required."})

        preset = preset_service.get_preset_by_name(preset_name)
        if not preset:
            return JSONResponse(status_code=404, content={"status": "error", "message": "Preset not found."})

        preset_service.apply_preset_to_config(preset)

        return JSONResponse(content={"status": "ok", "message": f"Preset '{preset_name}' applied to config."})

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})