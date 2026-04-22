"""System module: config access + runtime machine metadata."""

from __future__ import annotations

import copy
import importlib
import os
import platform
import socket
from datetime import datetime
from typing import Any, Callable, Optional

from constants.default_config import DEFAULT_CONFIG

_CONFIG_MODULE = "modules.system.config"


def _load_config_module(force_reload: bool = False):
    module = importlib.import_module(_CONFIG_MODULE)
    if force_reload:
        module = importlib.reload(module)
    return module


def _resolve_config_callable(name: str) -> Optional[Callable[..., Any]]:
    module = _load_config_module(force_reload=False)
    fn = getattr(module, name, None)
    if callable(fn):
        return fn

    module = _load_config_module(force_reload=True)
    fn = getattr(module, name, None)
    if callable(fn):
        return fn
    return None


def require_config_method(name: str) -> Callable[..., Any]:
    fn = _resolve_config_callable(name)
    if callable(fn):
        return fn
    raise AttributeError(f"Config service method '{name}' is unavailable")


def get_config(user_uuid: str | None = None) -> dict:
    fn = _resolve_config_callable("get_config")
    if not callable(fn):
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        return fn(user_uuid=user_uuid)
    except TypeError:
        return fn()


def get_config_value(path: str, default: Any = None, user_uuid: str | None = None) -> Any:
    fn = _resolve_config_callable("get_config_value")
    if not callable(fn):
        return default
    try:
        if user_uuid is not None:
            return fn(path, default, user_uuid=user_uuid)
        return fn(path, default)
    except TypeError:
        return fn(path, default)


def save_config(new_data: dict, user_uuid: str | None = None) -> None:
    fn = require_config_method("save_config")
    try:
        fn(new_data, user_uuid=user_uuid)
    except TypeError:
        fn(new_data)


def update_config_bulk(updates: dict, user_uuid: str | None = None):
    fn = require_config_method("update_config_bulk")
    try:
        return fn(updates, user_uuid=user_uuid)
    except TypeError:
        return fn(updates)


def set_config_value(path: str, value: Any, user_uuid: str | None = None) -> bool:
    fn = require_config_method("set_config_value")
    try:
        return bool(fn(path, value, user_uuid=user_uuid))
    except TypeError:
        return bool(fn(path, value))


def apply_preset_by_name(preset_name: str, user_uuid: str | None = None) -> bool:
    fn = require_config_method("apply_preset_by_name")
    try:
        return bool(fn(preset_name, user_uuid=user_uuid))
    except TypeError:
        return bool(fn(preset_name))


def redact_sensitive_config(config: dict | None) -> dict:
    fn = _resolve_config_callable("redact_sensitive_config")
    if not callable(fn):
        return copy.deepcopy(config or {})
    return fn(config)


def activate_user_context(user_uuid: str | None):
    if not user_uuid:
        return None
    fn = _resolve_config_callable("activate_user_context")
    if not callable(fn):
        return None
    return fn(user_uuid)


def reset_user_context(token) -> None:
    if token is None:
        return
    fn = _resolve_config_callable("reset_user_context")
    if not callable(fn):
        return
    fn(token)


def ensure_config_exists() -> None:
    fn = _resolve_config_callable("ensure_config_exists")
    if callable(fn):
        fn()


def migrate_owner_config_if_needed() -> bool:
    fn = _resolve_config_callable("migrate_owner_config_if_needed")
    if not callable(fn):
        return False
    return bool(fn())


def migrate_split_settings_if_needed() -> int:
    fn = _resolve_config_callable("migrate_split_settings_if_needed")
    if not callable(fn):
        return 0
    try:
        return int(fn())
    except Exception:
        return 0


def get_active_user_uuid() -> str | None:
    fn = _resolve_config_callable("get_active_user_uuid")
    if not callable(fn):
        return None
    try:
        value = fn()
    except Exception:
        return None
    if isinstance(value, str) and value.strip():
        return value
    return None


def get_owner_default_config() -> dict | None:
    fn = _resolve_config_callable("get_owner_default_config")
    if not callable(fn):
        return None
    try:
        value = fn()
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def get_active_character_name(
    user_uuid: str | None = None,
    default: str = "default_waifu",
) -> str:
    from modules.system import character as character_service

    resolved_user_uuid = user_uuid or get_active_user_uuid()
    character_name = character_service.resolve_active_character_name_for_user(
        resolved_user_uuid,
        fallback_char_name=str(default),
    )
    # Keep call-sites safe: history and generation expect character row to exist.
    try:
        character = character_service.get_or_create_character(character_name)
        return character.name
    except Exception:
        return character_name


def get_runtime_timezone_name() -> str:
    env_tz = (os.getenv("TZ") or "").strip()
    if env_tz:
        return env_tz
    try:
        return str(datetime.now().astimezone().tzinfo or "UTC")
    except Exception:
        return "UTC"


def get_machine_runtime_info() -> dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": os.cpu_count() or 0,
        "timezone": get_runtime_timezone_name(),
    }
