# ============================================================
# Module: history_service.py
# Purpose: Getting message history by character
# Used in: ollama_routes to return history
# Features:
# - Reads JSON files from local storage
# - Creates file if it does not exist
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