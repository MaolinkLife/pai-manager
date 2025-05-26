import json
import os
from typing import Any

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "char_name": "default_waifu",
    "user_name": "You",
    "voice": {
        "output_id": 0,
        "windows_output_id": 13,
        "language": "ru-RU",
        "use_rvc": False,
        "voice_language": "ru-RU-SvetlanaNeural",
    },
    "modules": {
        "vtube_studio": False,
        "whisper": False,
        "minecraft": False,
        "gaming": False,
        "alarm": False,
        "discord": False,
        "rag": False,
        "visual": False,
    },
    "api": {
        "type": "Ollama",
        "streaming": False,
        "model": "command-r:latest",
        "visual_model": "nsheth/llama-3-lumimaid-8b-v0.1-iq-imatrix",
        "token_limit": 4096,
        "message_pair_limit": 10,
    },
}

_config_cache = None


# Создаёт файл config.json с дефолтами, если его нет.
def ensure_config_exists():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)


def _load_config_from_file() -> dict:
    global _config_cache
    ensure_config_exists()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        _config_cache = json.load(f)
    return _config_cache


def _save_config_to_file(data: dict):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# Возвращает текущий конфиг (с кешированием).
def get_config() -> dict:
    global _config_cache
    if _config_cache is None:
        return _load_config_from_file()
    return _config_cache


# Перезаписывает весь конфиг новым содержимым.
def save_config(new_data: dict):
    global _config_cache
    _config_cache = new_data
    _save_config_to_file(_config_cache)


# Устанавливает значение по вложенному пути и сохраняет конфиг
def get_config_value(path: str, default: Any = None):
    keys = path.split(".")
    config = get_config()
    ref = config
    for key in keys:
        ref = ref.get(key)
        if ref is None:
            return default
    return ref


# Возвращает значение по пути "key1.key2". Если не найдено — возвращает default
def set_config_value(path: str, value: Any):
    keys = path.split(".")
    config = get_config()
    ref = config
    for key in keys[:-1]:
        ref = ref.setdefault(key, {})
    ref[keys[-1]] = value
    save_config(config)


def _recursive_update(existing: dict, updates: dict, path: str = ""):
    updated = []
    failed = []

    for key, value in updates.items():
        current_path = f"{path}.{key}" if path else key

        if key not in existing:
            failed.append({"path": current_path, "error": "Ключ не найден."})
            continue

        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            u, f = _recursive_update(existing[key], value, current_path)
            updated.extend(u)
            failed.extend(f)
        else:
            existing[key] = value
            updated.append(current_path)

    return updated, failed


def update_config_bulk(updates: dict):
    config = get_config()
    updated, failed = _recursive_update(config, updates)
    save_config(config)
    return updated, failed