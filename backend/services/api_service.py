# =========================================================
# Модуль: api_service.py
# Назначение: Формирование запроса для модели, включая system prompt и очистку истории
# Используется в: ollama_routes (для подготовки истории)
# Особенности:
# - Загружает YAML-профиль персонажа
# - Удаляет из истории лишние поля (например, timestamp)
# =========================================================

import yaml
import os
from services import ollama_service, config_service, database_service


def load_system_prompt() -> str:
    base_path = os.path.join(os.path.dirname(__file__), "..", "config", "characters")
    char_name = config_service.get_config_value("char_name", default="default")
    filename = f"{char_name}.yaml"
    full_path = os.path.join(base_path, filename)
    fallback_path = os.path.join(base_path, "default.yaml")

    try:
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("prompt", "")
        elif os.path.exists(fallback_path):
            with open(fallback_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data.get("prompt", "")
        else:
            print("[❌] Ни кастом, ни fallback не найдены")
            return "[System Error] Character prompt not found."
    except Exception as e:
        print(f"[Ошибка чтения character-файла]: {e}")
        return "[System Error] Prompt loading failed."


def build_chat_request(history, include_system=True):
    sanitized_history = [
        {k: v for k, v in msg.items() if k != "timestamp"} for msg in history
    ]
    if include_system:
        system_prompt = load_system_prompt()
        if system_prompt:
            sanitized_history.insert(0, {
                "role": "system",
                "content": system_prompt
            })
    return sanitized_history


def run_standard(history: list, temp_level: int, stop: list, max_tokens: int) -> str:
    full_history = build_chat_request(history)
    
    # Получаем имя персонажа
    char_name = config_service.get_config_value("char_name", "default")

    # Получаем последний message от user
    last_user_message = next(
        (msg for msg in reversed(history) if msg.get("role") == "user"), None
    )

    # Вызов модели через ollama_service
    response = ollama_service.api_standard(
        history=full_history,
        temp_level=temp_level,
        stop=stop,
        max_tokens=max_tokens,
    )

    # Извлекаем результат
    assistant_content = response.message.content.strip()

    # Сохраняем в историю (если последнее сообщение — от user)
    if last_user_message:
        database_service.add_message_to_history(
            character_name=char_name,
            role="user",
            content=last_user_message["content"],
            timestamp=last_user_message.get("timestamp"),
        )

    # Сохраняем ответ ассистента
    database_service.add_message_to_history(
        character_name=char_name,
        role="assistant",
        content=assistant_content,
        timestamp=response.created_at 
    )

    return assistant_content