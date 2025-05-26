from fastapi import APIRouter
from ollama._types import ResponseError
from services import ollama_service
from services import api_controller

router = APIRouter(prefix="/api/ollama", tags=["Ollama"])


# Отправка сообщений в Ollama (chat-запрос)
@router.post("/chat")
def chat(payload: dict):
    history = api_controller.build_chat_request(payload["history"])
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
