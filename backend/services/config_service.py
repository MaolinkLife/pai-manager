# ===========================================================
# Module: config_service.py
# Purpose: Managing LIM configuration. Loading, saving,
# updating and caching values ​​from config.json.
# Used in: services, utilities, core — anywhere configuration is needed
# Features:
# - Uses caching (_config_cache) to minimize I/O
# - Allows fine-grained modification of values ​​via get/set
# - Supports bulk update with validation (_recursive_update)
# ==========================================================
from typing import Dict, Any, Optional
import json
import os
from typing import Any
from utils.open_file_w_utf8 import open_utf8
from services.logger_service import log_audit_entry, AuditStatus

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config", "config.json")
PRESETS_PATH = os.path.join(
    os.path.dirname(__file__), "..", "config", "generation_presets.json"
)

# TODO: can be moved later to a file with constants
DEFAULT_CONFIG = {
    "user_id": None,
    "char_name": "default_waifu",
    "user_name": "You",
    "language": "ru-RU",
    "voice": {
        "enabled": False,
        "output_id": 0,
        "windows_output_id": 13,
        "language": "ru-RU",
        "use_rvc": False,
        "voice_language": "ru-RU-SvetlanaNeural",
        "use_windows_output": True,
        "streaming_tts": False,
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
    "generate_settings": {
        "name": "Default",
        "description": "Balanced generation style",
        "temperature": 1.27,
        "min_p": 0.0497,
        "top_p": 0.87,
        "top_k": 72,
        "repeat_penalty": 1.12,
        "stop": None,
        "num_predict": 1024,
    },
}

_config_cache = None


# Creates a config.json file with defaults if it does not exist.
def ensure_config_exists():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        log_audit_entry(
            event_type="config_created",
            msg="[Config Service]: Create Default Config",
            status=AuditStatus.SUCCESS,
            details={"status": "OK", "path": CONFIG_PATH},
            meta={
                "config_path": CONFIG_PATH,
                "defaultConfig": DEFAULT_CONFIG,
            },
        )


def _load_config_from_file() -> dict:
    global _config_cache
    ensure_config_exists()
    with open_utf8(CONFIG_PATH, "r") as f:
        _config_cache = json.load(f)
    return _config_cache


def _save_config_to_file(data: dict):
    with open_utf8(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# Returns the current config (with caching).
def get_config() -> dict:
    global _config_cache
    if _config_cache is None:
        return _load_config_from_file()
    return _config_cache.copy()


# Overwrites the entire config with new contents.
def save_config(new_data: dict):
    global _config_cache

    # Валидация
    is_valid, errors = validate_config(new_data)
    if not is_valid:
        log_audit_entry(
            event_type="config_validation_error",
            msg="[Config Service]: Config validation failed",
            status=AuditStatus.ERROR,
            details={"errors": errors, "config": new_data},
        )
        raise ValueError(f"Config validation failed: {errors}")

    _config_cache = new_data
    _save_config_to_file(_config_cache)
    log_audit_entry(
        event_type="config_saved",
        msg="[Config Service]: Save config file",
        status=AuditStatus.SUCCESS,
        details={"status": "OK", "keys": list(new_data.keys())},
        meta={"new_data": new_data},
    )


# Sets the value to the nested path and saves the config
def get_config_value(path: str, default: Any = None) -> Any:
    """Get nested config value by path like 'api.model'"""
    keys = path.split(".")
    config = get_config()
    ref = config

    for key in keys:
        if isinstance(ref, dict) and key in ref:
            ref = ref[key]
        else:
            return default
    return ref


# Returns the value at the path "key1.key2". If not found, returns default
def set_config_value(path: str, value: Any) -> bool:
    """Set nested config value by path like 'api.model'"""
    try:
        keys = path.split(".")
        config = get_config()
        ref = config

        # Дойдём до нужного уровня, создавая промежуточные словари если нужно
        for key in keys[:-1]:
            if key not in ref or not isinstance(ref[key], dict):
                ref[key] = {}
            ref = ref[key]

        # Установим значение
        ref[keys[-1]] = value
        save_config(config)
        return True
    except Exception as e:
        log_audit_entry(
            event_type="config_set_error",
            msg=f"[Config Service]: Error setting config value: {path}",
            status=AuditStatus.ERROR,
            details={"error": str(e), "path": path, "value": value},
        )
        return False


def _recursive_update(
    existing: dict, updates: dict, path: str = ""
) -> tuple[list, list]:
    """
    Рекурсивно обновляет конфиг, возвращает список успешно обновлённых и неудачных путей
    """
    updated = []
    failed = []

    for key, value in updates.items():
        current_path = f"{path}.{key}" if path else key

        # Защита от изменения user_id если он уже установлен
        if current_path == "user_id":
            if existing.get(key) not in [None, ""]:
                failed.append(
                    {
                        "path": current_path,
                        "error": "user_id is already set and cannot be changed.",
                    }
                )
                continue

        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            # Рекурсивно обновляем вложенные объекты
            u, f = _recursive_update(existing[key], value, current_path)
            updated.extend(u)
            failed.extend(f)
        else:
            # Обновляем простое значение
            old_value = existing.get(key)
            existing[key] = value
            updated.append(current_path)

            # Логируем изменение
            log_audit_entry(
                event_type="config_key_updated",
                msg=f"[Config Service]: Config key updated: {current_path}",
                status=AuditStatus.SUCCESS,
                details={
                    "path": current_path,
                    "old_value": old_value,
                    "new_value": value,
                },
            )

    return updated, failed


def validate_config(config: dict) -> tuple[bool, list]:
    """
    Базовая валидация конфига
    Возвращает (валиден, список ошибок)
    """
    errors = []

    # Проверим обязательные поля
    required_fields = ["user_id", "char_name", "user_name", "language"]
    for field in required_fields:
        if field not in config or config[field] is None:
            errors.append(f"Missing required field: {field}")

    # Проверим структуру voice
    if "voice" in config:
        voice = config["voice"]
        if not isinstance(voice, dict):
            errors.append("voice must be an object")
        elif voice.get("enabled") and not voice.get("voice_language"):
            errors.append("voice_language is required when voice is enabled")

    # Проверим API настройки
    if "api" in config:
        api = config["api"]
        if not isinstance(api, dict):
            errors.append("api must be an object")
        elif not api.get("model"):
            errors.append("api.model is required")

    return len(errors) == 0, errors


def update_config_bulk(updates: dict):
    config = get_config()
    updated, failed = _recursive_update(config, updates)
    save_config(config)

    log_audit_entry(
        event_type="config_updated_bulk",
        msg="[Config Service]: Update config fields",
        status=AuditStatus.SUCCESS,
        details={"updated": updated, "failed": failed},
        meta={
            "source": "config",
            "mode": "bulk",
            "config": config,
            "updated": updated,
            "failed": failed,
        },
    )

    # If char_name is updated, we create a character in the DB
    new_char_name = updates.get("char_name")
    # if new_char_name:
    #     database_service.get_or_create_character(new_char_name)

    return updated, failed


def load_generation_presets() -> list:
    if not os.path.exists(PRESETS_PATH):
        return []
    with open_utf8(PRESETS_PATH, "r") as f:
        return json.load(f)


def apply_preset_by_name(preset_name: str) -> bool:
    presets = load_generation_presets()
    matched = next((p for p in presets if p["name"] == preset_name), None)

    if not matched:
        return False

    config = get_config()
    config["generate_settings"] = matched
    save_config(config)
    return True


# Добавим в config_service.py:


def get_user_config(user_id: str) -> dict:
    """
    Получает конфиг для конкретного пользователя
    Пока возвращает общий конфиг, но готовимся к БД
    """
    config = get_config()
    if config.get("user_id") == user_id:
        return config
    # TODO: В будущем будет загрузка из БД
    return config


def save_user_config(user_id: str, config: dict) -> bool:
    """
    Сохраняет конфиг пользователя
    Пока сохраняет общий конфиг, но готовимся к БД
    """
    if get_config().get("user_id") == user_id:
        save_config(config)
        return True
    # TODO: В будущем будет сохранение в БД
    return False
