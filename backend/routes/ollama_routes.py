# =========================================================
# Модуль: ollama_routes.py
# Назначение: Эндпоинты для взаимодействия с моделью Ollama и получения истории
# Используется в: WebUI или других клиентах, посылающих запросы к LLM
# Особенности:
# - Работает через api_service (сборка запроса) и ollama_service (отправка запроса)
# - Имеет эндпоинты для получения списка моделей и истории
# =========================================================

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services import api_service, ollama_service
from services.history_service import get_history
from services import config_service

router = APIRouter(prefix="/api/ollama", tags=["Ollama"])


# Отправка сообщений в Ollama (chat-запрос)
@router.post("/chat")
def chat(payload: dict):
    history = api_service.build_chat_request(payload["history"])
    return {
        "response": ollama_service.api_standard(
            history=history,
            temp_level=payload.get("temp_level", 1),
            stop=payload.get("stop"),
            max_tokens=payload.get("max_tokens", 2048),
        )
    }


# Возвращает список доступных моделей Ollama.
@router.get("/models")
async def get_available_models():
    return ollama_service.get_models()


@router.get("/history")
async def fetch_history(limit: int = 32):
    try:
        char_name = config_service.get_config_value("char_name", "default_waifu")
        history = get_history(char_name, limit)
        return JSONResponse(content={"status": "ok", "history": history})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})