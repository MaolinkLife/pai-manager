# =========================================================
# Модуль: history_service.py
# Назначение: Получение истории сообщений по персонажу
# Используется в: ollama_routes для возврата истории
# Особенности:
# - Читает JSON-файлы из локального хранилища
# - Создаёт файл, если он отсутствует
# =========================================================

import os
import json

BASE_PATH = "storage/history"


def get_history(char_name: str, limit: int = 32):
    os.makedirs(BASE_PATH, exist_ok=True)
    filename = f"{char_name}_history.json"
    file_path = os.path.join(BASE_PATH, filename)

    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            messages = json.load(f)
    except json.JSONDecodeError:
        messages = []

    return messages[-limit:]