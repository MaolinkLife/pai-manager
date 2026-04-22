# ===========================================================
# Module: config_service.py
# Purpose: Managing LIM configuration in DB-first mode.
# Runtime does not depend on config.json.
# Used in: services, utilities, core — anywhere configuration is needed
# Features:
# - Uses caching (_config_cache) to minimize I/O
# - Allows fine-grained modification of values ​​via get/set
# - Supports bulk update with validation (_recursive_update)
# ==========================================================
from typing import Dict, Any, Optional
import copy
import json
import os
from datetime import datetime, timezone
from contextvars import ContextVar
from sqlalchemy.exc import OperationalError, ProgrammingError
from utils.open_file_w_utf8 import open_utf8
from modules.system.logger import log_audit_entry, AuditStatus
from models.config_model import CONFIG_PATHS
from models.models import (
    User,
    UserConfig,
    UserSettings,
    UserTtsSettings,
    UserVisionSettings,
)
from constants.default_config import DEFAULT_CONFIG
from modules.database.core import SessionLocal

LEGACY_PATH_MAP = {
    "user_id": "system.user_id",
    "user_name": "system.user_name",
    "char_name": "system.char_name",
    "language": "system.language",
}

SENSITIVE_CONFIG_KEY_HINTS = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "passphrase",
    "private_key",
)


def _rename_keys(data: Dict[str, Any], mapping: Dict[str, str]) -> None:
    """
    Rename keys in-place from camelCase to snake_case while preserving any already-converted values.
    """
    for old_key, new_key in mapping.items():
        if old_key not in data:
            continue
        value = data.pop(old_key)
        data.setdefault(new_key, value)


def _normalize_rag_section(config: Dict[str, Any]) -> None:
    """
    Normalize the RAG section to snake_case keys to keep backward compatibility
    with older camelCase configs.
    """
    rag = config.get("rag")
    if not isinstance(rag, dict):
        return

    _rename_keys(
        rag,
        {
            "embeddingModel": "embedding_model",
            "vectorDbPath": "vector_db_path",
            "chunkSize": "chunk_size",
            "chunkOverlap": "chunk_overlap",
            "topK": "top_k",
            "similarityThreshold": "similarity_threshold",
            "enableCaching": "enable_caching",
            "cacheTtl": "cache_ttl",
            "searchStrategy": "search_strategy",
        },
    )

    search_strategy = rag.get("search_strategy")
    if isinstance(search_strategy, dict):
        _rename_keys(
            search_strategy,
            {
                "sessionContext": "session_context",
                "dailySummary": "daily_summary",
                "longTermMemory": "long_term_memory",
            },
        )

        session_ctx = search_strategy.get("session_context")
        if isinstance(session_ctx, dict):
            _rename_keys(
                session_ctx,
                {
                    "maxMessages": "max_messages",
                    "lookBackToToday": "look_back_to_today",
                },
            )

        daily_summary = search_strategy.get("daily_summary")
        if isinstance(daily_summary, dict):
            _rename_keys(
                daily_summary,
                {
                    "lookBackDays": "look_back_days",
                    "useTags": "use_tags",
                },
            )

        long_term_memory = search_strategy.get("long_term_memory")
        if isinstance(long_term_memory, dict):
            _rename_keys(
                long_term_memory,
                {
                    "vectorSearch": "vector_search",
                    "graphSearch": "graph_search",
                    "priorityRules": "priority_rules",
                },
            )

        fallback = search_strategy.get("fallback")
        if isinstance(fallback, dict):
            _rename_keys(
                fallback,
                {
                    "askUser": "ask_user",
                    "autoLearn": "auto_learn",
                },
            )

    memory_section = rag.get("memory")
    if isinstance(memory_section, dict):
        facts = memory_section.get("facts")
        if isinstance(facts, dict):
            _rename_keys(
                facts,
                {
                    "priorityRules": "priority_rules",
                    "autoUpdate": "auto_update",
                },
            )

    # Ensure nested dictionaries exist when snake_case keys were newly created.
    if "search_strategy" not in rag and "searchStrategy" in config.get("rag", {}):
        rag["search_strategy"] = rag.pop("searchStrategy")


def normalize_config_structure(config: dict | None) -> dict:
    """
    Ensures legacy top-level identity fields live under system section.
    Removes duplicated root keys while keeping existing values.
    """
    if not isinstance(config, dict):
        config = {}

    normalized = copy.deepcopy(config)

    def _merge_missing(target: dict, defaults: dict) -> None:
        for key, default_value in (defaults or {}).items():
            if key not in target:
                target[key] = copy.deepcopy(default_value)
                continue
            if isinstance(target.get(key), dict) and isinstance(default_value, dict):
                _merge_missing(target[key], default_value)

    system_section = normalized.get("system")
    if not isinstance(system_section, dict):
        system_section = {}

    # Move legacy top-level keys into the system section
    for legacy_key, mapped_path in LEGACY_PATH_MAP.items():
        system_key = mapped_path.split(".")[-1]
        if legacy_key in normalized:
            legacy_value = normalized.pop(legacy_key)
            if legacy_value is not None and system_section.get(system_key) in [
                None,
                "",
            ]:
                system_section[system_key] = legacy_value

    # Ensure defaults exist for required system fields
    default_system = DEFAULT_CONFIG.get("system", {})
    for key, default_value in default_system.items():
        if key not in system_section:
            system_section[key] = copy.deepcopy(default_value)

    normalized["system"] = system_section

    # Ensure modules section exists and includes all known flags.
    modules_defaults = DEFAULT_CONFIG.get("modules", {})
    modules_section = normalized.get("modules")
    if not isinstance(modules_section, dict):
        modules_section = copy.deepcopy(modules_defaults)
    else:
        _merge_missing(modules_section, modules_defaults)
    normalized["modules"] = modules_section

    # Ensure connector section exists (user tunnel settings).
    if not isinstance(normalized.get("connector"), dict):
        normalized["connector"] = copy.deepcopy(DEFAULT_CONFIG.get("connector", {}))
    else:
        connector_defaults = DEFAULT_CONFIG.get("connector", {})
        tunneling_defaults = (
            connector_defaults.get("tunneling", {})
            if isinstance(connector_defaults, dict)
            else {}
        )
        connector = normalized["connector"]
        tunneling = connector.get("tunneling")
        if not isinstance(tunneling, dict):
            connector["tunneling"] = copy.deepcopy(tunneling_defaults)
        else:
            for key, default_value in tunneling_defaults.items():
                if key not in tunneling:
                    tunneling[key] = copy.deepcopy(default_value)

    _normalize_rag_section(normalized)

    memory_section = normalized.get("memory")
    if not isinstance(memory_section, dict):
        memory_section = copy.deepcopy(DEFAULT_CONFIG.get("memory", {}))
    else:
        if "deepMemoryEnabled" in memory_section and "deep_memory_enabled" not in memory_section:
            memory_section["deep_memory_enabled"] = bool(
                memory_section.get("deepMemoryEnabled")
            )
        if "forceDeepMemory" in memory_section and "force_deep_memory" not in memory_section:
            memory_section["force_deep_memory"] = bool(
                memory_section.get("forceDeepMemory")
            )
        memory_defaults = DEFAULT_CONFIG.get("memory", {})
        for key, default_value in memory_defaults.items():
            if key not in memory_section:
                memory_section[key] = copy.deepcopy(default_value)
    normalized["memory"] = memory_section

    telegram_defaults = DEFAULT_CONFIG.get("telegram", {})
    telegram_section = normalized.get("telegram")
    if not isinstance(telegram_section, dict):
        telegram_section = copy.deepcopy(telegram_defaults)
    else:
        _merge_missing(telegram_section, telegram_defaults)
    normalized["telegram"] = telegram_section

    synthesis_defaults = DEFAULT_CONFIG.get("synthesis", {})
    synthesis_section = normalized.get("synthesis")
    if not isinstance(synthesis_section, dict):
        synthesis_section = copy.deepcopy(synthesis_defaults)
    else:
        _merge_missing(synthesis_section, synthesis_defaults)
    normalized["synthesis"] = synthesis_section

    communication_defaults = DEFAULT_CONFIG.get("communication", {})
    communication_section = normalized.get("communication")
    if not isinstance(communication_section, dict):
        communication_section = copy.deepcopy(communication_defaults)
    else:
        _merge_missing(communication_section, communication_defaults)
    priority_list = communication_section.get("priority")
    channels_cfg = communication_section.get("channels")
    if isinstance(priority_list, list) and isinstance(channels_cfg, dict):
        primary = None
        for item in priority_list:
            channel_name = str(item or "").strip()
            if channel_name in ("main_chat", "telegram"):
                primary = channel_name
                break
        if primary == "main_chat":
            telegram_channel_cfg = channels_cfg.get("telegram")
            if isinstance(telegram_channel_cfg, dict):
                telegram_channel_cfg["allow_fallback"] = False
    normalized["communication"] = communication_section

    return normalized


PRESETS_PATH = os.path.join(os.path.dirname(__file__), "..", CONFIG_PATHS["presets"])
_active_user_uuid: ContextVar[Optional[str]] = ContextVar(
    "config_active_user_uuid", default=None
)


# Legacy compatibility hook. Runtime no longer uses config.json.
def ensure_config_exists():
    return


def activate_user_context(user_uuid: Optional[str]):
    return _active_user_uuid.set(user_uuid)


def reset_user_context(token) -> None:
    _active_user_uuid.reset(token)


def get_active_user_uuid() -> Optional[str]:
    return _active_user_uuid.get()


def _resolve_user_uuid(user_uuid: Optional[str]) -> Optional[str]:
    if user_uuid:
        return user_uuid
    return get_active_user_uuid()


def _build_seed_config_for_user(user_uuid: str) -> dict:
    normalized = normalize_config_structure(copy.deepcopy(DEFAULT_CONFIG))
    normalized.setdefault("system", {})
    normalized["system"]["user_id"] = user_uuid
    return normalized


def _load_user_config_from_db(user_uuid: str) -> Optional[dict]:
    session = SessionLocal()
    try:
        record = session.query(UserConfig).filter_by(user_uuid=user_uuid).first()
        if not record:
            return None
        try:
            payload = json.loads(record.config_json or "{}")
        except Exception:
            payload = {}
        normalized = normalize_config_structure(payload)
        _apply_split_settings_overrides(normalized, user_uuid)
        normalized.setdefault("system", {})
        normalized["system"]["user_id"] = user_uuid
        return normalized
    finally:
        session.close()


def _save_user_config_to_db(user_uuid: str, config_data: dict) -> None:
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.uuid == user_uuid).first()
        if not user:
            raise ValueError("User not found for config persistence")

        record = session.query(UserConfig).filter_by(user_uuid=user_uuid).first()
        if not record:
            record = UserConfig(user_uuid=user_uuid)
            session.add(record)
            session.flush()

        record.config_json = json.dumps(config_data, ensure_ascii=False)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ensure_user_config_exists(user_uuid: str) -> dict:
    existing = _load_user_config_from_db(user_uuid)
    if existing is not None:
        return existing

    seed = _build_seed_config_for_user(user_uuid)
    _persist_split_settings(user_uuid, seed)
    _save_user_config_to_db(user_uuid, _strip_split_settings(seed))
    return seed


def _strip_split_settings(config_data: dict) -> dict:
    sanitized = copy.deepcopy(config_data or {})
    sanitized.pop("voice", None)
    sanitized.pop("vision", None)
    return sanitized


def _load_user_tts_settings_from_db(user_uuid: str) -> Optional[dict]:
    session = SessionLocal()
    try:
        record = session.query(UserTtsSettings).filter_by(user_uuid=user_uuid).first()
        if not record:
            return None
        try:
            payload = json.loads(record.settings_json or "{}")
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else None
    finally:
        session.close()


def _save_user_tts_settings_to_db(user_uuid: str, settings_data: dict) -> None:
    session = SessionLocal()
    try:
        record = session.query(UserTtsSettings).filter_by(user_uuid=user_uuid).first()
        if not record:
            record = UserTtsSettings(user_uuid=user_uuid)
            session.add(record)
            session.flush()
        record.settings_json = json.dumps(settings_data or {}, ensure_ascii=False)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _load_user_vision_settings_from_db(user_uuid: str) -> Optional[dict]:
    session = SessionLocal()
    try:
        record = session.query(UserVisionSettings).filter_by(user_uuid=user_uuid).first()
        if not record:
            return None
        try:
            payload = json.loads(record.settings_json or "{}")
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else None
    finally:
        session.close()


def _save_user_vision_settings_to_db(user_uuid: str, settings_data: dict) -> None:
    session = SessionLocal()
    try:
        record = session.query(UserVisionSettings).filter_by(user_uuid=user_uuid).first()
        if not record:
            record = UserVisionSettings(user_uuid=user_uuid)
            session.add(record)
            session.flush()
        record.settings_json = json.dumps(settings_data or {}, ensure_ascii=False)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _persist_split_settings(user_uuid: str, config_data: dict) -> None:
    if not isinstance(config_data, dict):
        return
    voice = config_data.get("voice")
    vision = config_data.get("vision")
    if isinstance(voice, dict):
        _save_user_tts_settings_to_db(user_uuid, voice)
    if isinstance(vision, dict):
        _save_user_vision_settings_to_db(user_uuid, vision)


def _apply_split_settings_overrides(config_data: dict, user_uuid: str) -> None:
    if not isinstance(config_data, dict):
        return
    tts_settings = _load_user_tts_settings_from_db(user_uuid)
    vision_settings = _load_user_vision_settings_from_db(user_uuid)
    if isinstance(tts_settings, dict):
        config_data["voice"] = copy.deepcopy(tts_settings)
    if isinstance(vision_settings, dict):
        config_data["vision"] = copy.deepcopy(vision_settings)


def _pick_owner_like_user(session) -> Optional[User]:
    try:
        owners = (
            session.query(User)
            .filter(User.role == "owner", User.is_active == True)
            .all()
        )
    except (OperationalError, ProgrammingError):
        # Fresh DB: schema is not created yet, so owner lookup must be skipped.
        return None
    if owners:
        owners.sort(
            key=lambda u: (
                u.last_login_at or datetime.min.replace(tzinfo=timezone.utc),
                u.created_at or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        return owners[0]

    trusted = (
        session.query(User)
        .filter(User.trust_level >= 2, User.is_active == True)
        .all()
    )
    if trusted:
        trusted.sort(
            key=lambda u: (
                u.last_login_at or datetime.min.replace(tzinfo=timezone.utc),
                u.created_at or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        return trusted[0]

    fallbacks = (
        session.query(User)
        .filter(User.password_hash.isnot(None), User.is_active == True)
        .all()
    )
    if not fallbacks:
        return None
    fallbacks.sort(
        key=lambda u: (
            u.last_login_at or datetime.min.replace(tzinfo=timezone.utc),
            u.created_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    return fallbacks[0]


def _is_sensitive_config_key(key: str) -> bool:
    key_norm = (key or "").strip().lower()
    if not key_norm:
        return False
    return any(hint in key_norm for hint in SENSITIVE_CONFIG_KEY_HINTS)


def redact_sensitive_config(config: Dict[str, Any] | None) -> dict:
    """
    Returns a deep copy of config with credential-like fields removed.
    Used for anonymous/public reads where config structure is needed,
    but secrets must stay backend-only.
    """
    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                if _is_sensitive_config_key(key):
                    sanitized[key] = ""
                    continue
                sanitized[key] = _walk(item)
            return sanitized
        if isinstance(value, list):
            return [_walk(item) for item in value]
        return value

    if not isinstance(config, dict):
        return {}
    return _walk(copy.deepcopy(config))


def _get_owner_user_uuid() -> Optional[str]:
    session = SessionLocal()
    try:
        owner_like = _pick_owner_like_user(session)
        return owner_like.uuid if owner_like else None
    finally:
        session.close()


def get_owner_default_config() -> Optional[dict]:
    owner_uuid = _get_owner_user_uuid()
    if not owner_uuid:
        return None
    return ensure_user_config_exists(owner_uuid)


def migrate_owner_config_if_needed() -> bool:
    """
    One-time migration:
    - if an authenticated owner exists and does not have user_configs row yet,
      create it from DEFAULT_CONFIG seed.
    """
    session = SessionLocal()
    try:
        owner = _pick_owner_like_user(session)
        if not owner:
            return False

        existing = session.query(UserConfig).filter_by(user_uuid=owner.uuid).first()
        if existing:
            return False

        seed = _build_seed_config_for_user(owner.uuid)
        session.add(
            UserConfig(
                user_uuid=owner.uuid,
                config_json=json.dumps(seed, ensure_ascii=False),
            )
        )

        settings = session.query(UserSettings).filter_by(user_uuid=owner.uuid).first()
        if settings:
            lang = seed.get("system", {}).get("language")
            if lang:
                settings.language = lang

        session.commit()
        log_audit_entry(
            event_type="config_owner_migrated",
            msg="[Config Service]: Migrated owner config to DB.",
            status=AuditStatus.SUCCESS,
            details={"user_uuid": owner.uuid},
        )
        return True
    except Exception as exc:
        session.rollback()
        log_audit_entry(
            event_type="config_owner_migration_failed",
            msg="[Config Service]: Owner config migration failed.",
            status=AuditStatus.ERROR,
            details={"error": str(exc)},
        )
        return False
    finally:
        session.close()


def migrate_split_settings_if_needed() -> int:
    session = SessionLocal()
    migrated_count = 0
    try:
        records = session.query(UserConfig).all()
        for record in records:
            user_uuid = record.user_uuid
            try:
                payload = json.loads(record.config_json or "{}")
            except Exception:
                payload = {}
            if not isinstance(payload, dict):
                payload = {}

            moved = False
            voice = payload.get("voice")
            vision = payload.get("vision")
            if isinstance(voice, dict):
                _save_user_tts_settings_to_db(user_uuid, voice)
                payload.pop("voice", None)
                moved = True
            if isinstance(vision, dict):
                _save_user_vision_settings_to_db(user_uuid, vision)
                payload.pop("vision", None)
                moved = True

            if moved:
                record.config_json = json.dumps(payload, ensure_ascii=False)
                migrated_count += 1

        if migrated_count:
            session.commit()
            log_audit_entry(
                event_type="config_split_migrated",
                msg="[Config Service]: Split settings migrated to dedicated tables.",
                status=AuditStatus.SUCCESS,
                details={"users_migrated": migrated_count},
            )
        return migrated_count
    except Exception as exc:
        session.rollback()
        log_audit_entry(
            event_type="config_split_migration_failed",
            msg="[Config Service]: Split settings migration failed.",
            status=AuditStatus.ERROR,
            details={"error": str(exc)},
        )
        return 0
    finally:
        session.close()


# Returns the current config (with caching).
def get_config(user_uuid: Optional[str] = None) -> dict:
    resolved_user_uuid = _resolve_user_uuid(user_uuid)
    if resolved_user_uuid:
        return ensure_user_config_exists(resolved_user_uuid)

    owner_default = get_owner_default_config()
    if owner_default is not None:
        return owner_default
    return normalize_config_structure(copy.deepcopy(DEFAULT_CONFIG))


# Overwrites the entire config with new contents.
def save_config(new_data: dict, user_uuid: Optional[str] = None):
    resolved_user_uuid = _resolve_user_uuid(user_uuid) or _get_owner_user_uuid()

    normalized_data = normalize_config_structure(new_data)
    if resolved_user_uuid:
        normalized_data.setdefault("system", {})
        normalized_data["system"]["user_id"] = resolved_user_uuid

    # Validation
    is_valid, errors = validate_config(normalized_data)
    if not is_valid:
        log_audit_entry(
            event_type="config_validation_error",
            msg="[Config Service]: Config validation failed",
            status=AuditStatus.ERROR,
            details={"errors": errors, "config": normalized_data},
        )
        raise ValueError(f"Config validation failed: {errors}")

    if not resolved_user_uuid:
        raise ValueError("No target user for config persistence")

    _persist_split_settings(resolved_user_uuid, normalized_data)
    _save_user_config_to_db(
        resolved_user_uuid,
        _strip_split_settings(normalized_data),
    )
    log_audit_entry(
        event_type="config_saved_user",
        msg="[Config Service]: Save user config to DB",
        status=AuditStatus.SUCCESS,
        details={
            "status": "OK",
            "keys": list(normalized_data.keys()),
            "user_uuid": resolved_user_uuid,
        },
        meta={"new_data": normalized_data, "user_uuid": resolved_user_uuid},
    )


# Sets the value to the nested path and saves the config
def get_config_value(
    path: str, default: Any = None, user_uuid: Optional[str] = None
) -> Any:
    """Get nested config value by path like 'api.model'"""
    path = LEGACY_PATH_MAP.get(path, path)
    keys = path.split(".")
    config = get_config(user_uuid=user_uuid)
    ref = config

    for key in keys:
        if isinstance(ref, dict) and key in ref:
            ref = ref[key]
        else:
            return default
    return ref


# Returns the value at the path "key1.key2". If not found, returns default
def set_config_value(path: str, value: Any, user_uuid: Optional[str] = None) -> bool:
    """Set nested config value by path like 'api.model'"""
    try:
        path = LEGACY_PATH_MAP.get(path, path)
        keys = path.split(".")
        config = get_config(user_uuid=user_uuid)
        ref = config

        # Reach the required level, creating intermediate dicts when necessary
        for key in keys[:-1]:
            if key not in ref or not isinstance(ref[key], dict):
                ref[key] = {}
            ref = ref[key]

        # Assign the value
        ref[keys[-1]] = value
        save_config(config, user_uuid=user_uuid)
        return True
    except Exception as e:
        log_audit_entry(
            event_type="config_set_error",
            msg=f"[Config Service]: Error setting config value: {path}",
            status=AuditStatus.ERROR,
            details={"error": str(e), "path": path, "value": value},
            message_args={"path": path},
        )
        return False


def _recursive_update(
    existing: dict, updates: dict, path: str = ""
) -> tuple[list, list]:
    """
    Recursively update the config, returning lists of success and failure paths.
    """
    updated = []
    failed = []

    log_audit_entry(
        event_type="config_debug_recursive_start",
        msg="[Config Service]: Starting recursive update",
        status=AuditStatus.INFO,
        details={
            "path": path,
            "updates_keys": (
                list(updates.keys()) if isinstance(updates, dict) else "not_dict"
            ),
            "existing_type": type(existing).__name__,
        },
    )

    for key, value in updates.items():
        current_path = f"{path}.{key}" if path else key

        log_audit_entry(
            event_type="config_debug_recursive_item",
            msg="[Config Service]: Processing item in recursive update",
            status=AuditStatus.INFO,
            details={
                "current_path": current_path,
                "key": key,
                "value_type": type(value).__name__,
                "value": (
                    str(value)[:200] + "..."
                    if isinstance(value, (dict, list)) and len(str(value)) > 200
                    else value
                ),
            },
        )

        # Protect existing user_id from being overwritten
        if current_path in ("user_id", "system.user_id"):
            current_container = existing if isinstance(existing, dict) else {}
            if current_container.get(key) not in [None, ""]:
                failed.append(
                    {
                        "path": current_path,
                        "error": "user_id is already set and cannot be changed.",
                    }
                )
                continue

        if isinstance(value, dict) and isinstance(existing.get(key), dict):
            # Recursively update nested dictionaries
            log_audit_entry(
                event_type="config_debug_recursive_nested",
                msg="[Config Service]: Recursively updating nested dict",
                status=AuditStatus.INFO,
                details={
                    "path": current_path,
                    "key": key,
                },
            )
            u, f = _recursive_update(existing[key], value, current_path)
            updated.extend(u)
            failed.extend(f)
        else:
            # Update a simple value
            old_value = existing.get(key)
            existing[key] = value
            updated.append(current_path)

            # Log the change
            log_audit_entry(
                event_type="config_key_updated",
                msg=f"[Config Service]: Config key updated: {current_path}",
                status=AuditStatus.SUCCESS,
                details={
                    "path": current_path,
                    "old_value": str(old_value)[:100] if old_value else old_value,
                    "new_value": str(value)[:100] if value else value,
                },
                message_args={"path": current_path},
            )

    log_audit_entry(
        event_type="config_debug_recursive_end",
        msg="[Config Service]: Finished recursive update",
        status=AuditStatus.INFO,
        details={
            "path": path,
            "updated_count": len(updated),
            "failed_count": len(failed),
        },
    )

    return updated, failed


def validate_config(config: dict) -> tuple[bool, list]:
    """
    Basic validation of the config.
    Returns (is_valid, list_of_errors).
    """
    errors = []

    # Validate system section
    system_cfg = config.get("system")
    if not isinstance(system_cfg, dict):
        errors.append("system must be an object")
    else:
        # Для user_id делаем отдельную проверку - он может быть None при создании дефолтного конфига
        # Но если он есть, то должен быть не пустым
        user_id = system_cfg.get("user_id")
        if user_id is not None and user_id == "":
            errors.append("system.user_id cannot be empty string")

    # Validate voice section
    if "voice" in config:
        voice = config["voice"]
        if not isinstance(voice, dict):
            errors.append("voice must be an object")
        elif voice.get("enabled") and not voice.get("voice_language"):
            errors.append("voice_language is required when voice is enabled")

    # Validate API settings
    if "api" in config:
        api = config["api"]
        if not isinstance(api, dict):
            errors.append("api must be an object")
        else:
            providers = api.get("providers")
            if providers is None or not isinstance(providers, dict):
                errors.append("api.providers must be an object")
            else:
                for name, provider_cfg in providers.items():
                    if not isinstance(provider_cfg, dict):
                        errors.append(f"api.providers.{name} must be an object")
            active_provider = api.get("active_provider")
            if active_provider and providers and active_provider not in providers:
                errors.append("api.active_provider must exist inside api.providers")
            if not active_provider:
                errors.append("api.active_provider is required")

    if "memory" in config:
        memory_cfg = config["memory"]
        if not isinstance(memory_cfg, dict):
            errors.append("memory must be an object")
        else:
            recent_limit = memory_cfg.get("recent_limit")
            if recent_limit is not None and (
                not isinstance(recent_limit, int) or recent_limit <= 0
            ):
                errors.append("memory.recent_limit must be a positive integer")
            similarity = memory_cfg.get("similarity_threshold")
            if similarity is not None and not isinstance(similarity, (float, int)):
                errors.append("memory.similarity_threshold must be a number")

    if "moral" in config:
        moral_cfg = config["moral"]
        if not isinstance(moral_cfg, dict):
            errors.append("moral must be an object")
        else:
            providers = moral_cfg.get("providers", {})
            if not isinstance(providers, dict):
                errors.append("moral.providers must be an object")
            else:
                for name, provider_cfg in providers.items():
                    if name != "heuristic" and not isinstance(provider_cfg, dict):
                        errors.append(f"moral.providers.{name} must be an object")
            active_provider = moral_cfg.get("active_provider")
            if not isinstance(active_provider, str) or not active_provider:
                errors.append("moral.active_provider is required")
            fallback_order = moral_cfg.get("fallback_order")
            if fallback_order is not None and not isinstance(fallback_order, list):
                errors.append("moral.fallback_order must be a list")
            if (
                isinstance(active_provider, str)
                and isinstance(providers, dict)
                and active_provider not in providers
                and active_provider != "heuristic"
            ):
                errors.append("moral.active_provider must exist inside moral.providers")

    # Validate newly added sections
    if "system" in config:
        system_cfg = config["system"]
        if not isinstance(system_cfg, dict):
            errors.append("system must be an object")
        else:
            runtime_cfg = system_cfg.get("runtime")
            if runtime_cfg is not None and not isinstance(runtime_cfg, dict):
                errors.append("system.runtime must be an object")
            elif isinstance(runtime_cfg, dict):
                profile = runtime_cfg.get("model_memory_profile")
                if profile is not None:
                    profile_norm = str(profile).strip().lower()
                    if profile_norm not in {"low_memory_strict", "balanced", "max_speed"}:
                        errors.append(
                            "system.runtime.model_memory_profile must be one of: low_memory_strict, balanced, max_speed"
                        )

    if "connector" in config:
        connector_cfg = config["connector"]
        if not isinstance(connector_cfg, dict):
            errors.append("connector must be an object")
        else:
            tunneling_cfg = connector_cfg.get("tunneling")
            if tunneling_cfg is not None and not isinstance(tunneling_cfg, dict):
                errors.append("connector.tunneling must be an object")

    if "audio" in config and not isinstance(config["audio"], dict):
        errors.append("audio must be an object")

    if "vision" in config and not isinstance(config["vision"], dict):
        errors.append("vision must be an object")

    if "rag" in config:
        rag = config["rag"]
        if not isinstance(rag, dict):
            errors.append("rag must be an object")
        elif rag.get("enabled") and not rag.get("embedding_model"):
            errors.append("rag.embedding_model is required when rag is enabled")

    if "telegram" in config:
        telegram_cfg = config["telegram"]
        if not isinstance(telegram_cfg, dict):
            errors.append("telegram must be an object")
        else:
            if telegram_cfg.get("enabled"):
                api_id = telegram_cfg.get("api_id")
                if not isinstance(api_id, int) or api_id <= 0:
                    errors.append("telegram.api_id must be a positive integer when telegram is enabled")
                api_hash = telegram_cfg.get("api_hash")
                if not isinstance(api_hash, str) or not api_hash.strip():
                    errors.append("telegram.api_hash is required when telegram is enabled")
            routing = telegram_cfg.get("routing")
            if routing is not None and not isinstance(routing, dict):
                errors.append("telegram.routing must be an object")
            lockdown = telegram_cfg.get("lockdown")
            if lockdown is not None and not isinstance(lockdown, dict):
                errors.append("telegram.lockdown must be an object")
            elif isinstance(lockdown, dict):
                owner_chat_id = lockdown.get("owner_chat_id")
                if owner_chat_id is not None and (
                    not isinstance(owner_chat_id, int) or owner_chat_id < 0
                ):
                    errors.append("telegram.lockdown.owner_chat_id must be a non-negative integer")
            presence = telegram_cfg.get("presence")
            if presence is not None and not isinstance(presence, dict):
                errors.append("telegram.presence must be an object")
            initiative = telegram_cfg.get("initiative")
            if initiative is not None and not isinstance(initiative, dict):
                errors.append("telegram.initiative must be an object")
            elif isinstance(initiative, dict):
                check_every_seconds = initiative.get("check_every_seconds")
                if check_every_seconds is not None and (
                    not isinstance(check_every_seconds, int) or check_every_seconds <= 0
                ):
                    errors.append(
                        "telegram.initiative.check_every_seconds must be a positive integer"
                    )
                idle_minutes = initiative.get("idle_minutes")
                if idle_minutes is not None and (
                    not isinstance(idle_minutes, int) or idle_minutes <= 0
                ):
                    errors.append("telegram.initiative.idle_minutes must be a positive integer")
                min_gap_minutes = initiative.get("min_gap_minutes")
                if min_gap_minutes is not None and (
                    not isinstance(min_gap_minutes, int) or min_gap_minutes < 0
                ):
                    errors.append(
                        "telegram.initiative.min_gap_minutes must be a non-negative integer"
                    )
                bootstrap_max_chats = initiative.get("bootstrap_max_chats")
                if bootstrap_max_chats is not None and (
                    not isinstance(bootstrap_max_chats, int) or bootstrap_max_chats <= 0
                ):
                    errors.append(
                        "telegram.initiative.bootstrap_max_chats must be a positive integer"
                    )
                for bool_key in (
                    "enabled",
                    "allow_private",
                    "allow_groups",
                    "owner_chat_only",
                ):
                    value = initiative.get(bool_key)
                    if value is not None and not isinstance(value, bool):
                        errors.append(f"telegram.initiative.{bool_key} must be boolean")
                bootstrap_flag = initiative.get("bootstrap_from_catalog")
                if bootstrap_flag is not None and not isinstance(bootstrap_flag, bool):
                    errors.append(
                        "telegram.initiative.bootstrap_from_catalog must be boolean"
                    )
            autonomous_inbox = telegram_cfg.get("autonomous_inbox")
            if autonomous_inbox is not None and not isinstance(autonomous_inbox, dict):
                errors.append("telegram.autonomous_inbox must be an object")
            elif isinstance(autonomous_inbox, dict):
                for int_key in ("check_every_seconds", "max_candidates", "max_actions_per_cycle"):
                    value = autonomous_inbox.get(int_key)
                    if value is not None and (not isinstance(value, int) or value <= 0):
                        errors.append(
                            f"telegram.autonomous_inbox.{int_key} must be a positive integer"
                        )
                for bool_key in ("enabled", "include_private", "include_groups", "include_channels"):
                    value = autonomous_inbox.get(bool_key)
                    if value is not None and not isinstance(value, bool):
                        errors.append(f"telegram.autonomous_inbox.{bool_key} must be boolean")
            anti_repeat = telegram_cfg.get("anti_repeat")
            if anti_repeat is not None and not isinstance(anti_repeat, dict):
                errors.append("telegram.anti_repeat must be an object")
            elif isinstance(anti_repeat, dict):
                for key in (
                    "history_size",
                    "semantic_history_size",
                    "retry_attempts",
                    "retry_memory_chars",
                ):
                    value = anti_repeat.get(key)
                    if value is not None and (not isinstance(value, int) or value <= 0):
                        errors.append(f"telegram.anti_repeat.{key} must be a positive integer")
                for key in (
                    "similarity_threshold",
                    "jaccard_threshold",
                    "semantic_max_similarity_threshold",
                    "semantic_avg_similarity_threshold",
                ):
                    value = anti_repeat.get(key)
                    if value is not None and not isinstance(value, (float, int)):
                        errors.append(f"telegram.anti_repeat.{key} must be a number")
            orchestration = telegram_cfg.get("orchestration")
            if orchestration is not None and not isinstance(orchestration, dict):
                errors.append("telegram.orchestration must be an object")
            elif isinstance(orchestration, dict):
                max_rounds = orchestration.get("max_rounds")
                if max_rounds is not None and (
                    not isinstance(max_rounds, int) or max_rounds <= 0
                ):
                    errors.append("telegram.orchestration.max_rounds must be a positive integer")
                max_tool_output_chars = orchestration.get("max_tool_output_chars")
                if max_tool_output_chars is not None and (
                    not isinstance(max_tool_output_chars, int) or max_tool_output_chars <= 0
                ):
                    errors.append(
                        "telegram.orchestration.max_tool_output_chars must be a positive integer"
                    )
                max_manual_sends = orchestration.get("max_manual_sends_per_turn")
                if max_manual_sends is not None and (
                    not isinstance(max_manual_sends, int) or max_manual_sends <= 0
                ):
                    errors.append(
                        "telegram.orchestration.max_manual_sends_per_turn must be a positive integer"
                    )
                max_no_tool_retries = orchestration.get("max_no_tool_retries")
                if max_no_tool_retries is not None and (
                    not isinstance(max_no_tool_retries, int) or max_no_tool_retries < 0
                ):
                    errors.append(
                        "telegram.orchestration.max_no_tool_retries must be a non-negative integer"
                    )
                tools_cfg = orchestration.get("tools")
                if tools_cfg is not None and not isinstance(tools_cfg, dict):
                    errors.append("telegram.orchestration.tools must be an object")

    if "communication" in config:
        communication_cfg = config["communication"]
        if not isinstance(communication_cfg, dict):
            errors.append("communication must be an object")
        else:
            priority = communication_cfg.get("priority")
            channels = communication_cfg.get("channels")
            if priority is not None and not isinstance(priority, list):
                errors.append("communication.priority must be a list")
            if channels is None or not isinstance(channels, dict):
                errors.append("communication.channels must be an object")
            else:
                enabled_count = 0
                for channel_name in ("main_chat", "telegram"):
                    channel_cfg = channels.get(channel_name)
                    if channel_cfg is None:
                        continue
                    if not isinstance(channel_cfg, dict):
                        errors.append(f"communication.channels.{channel_name} must be an object")
                        continue
                    enabled = channel_cfg.get("enabled")
                    if enabled is not None and not isinstance(enabled, bool):
                        errors.append(
                            f"communication.channels.{channel_name}.enabled must be boolean"
                        )
                    if bool(enabled):
                        enabled_count += 1
                    allow_fallback = channel_cfg.get("allow_fallback")
                    if allow_fallback is not None and not isinstance(allow_fallback, bool):
                        errors.append(
                            f"communication.channels.{channel_name}.allow_fallback must be boolean"
                        )

                # Hard rule: at least one channel must stay enabled.
                if enabled_count <= 0:
                    errors.append("communication requires at least one enabled channel")

                if isinstance(priority, list):
                    valid_names = {"main_chat", "telegram"}
                    primary = None
                    for item in priority:
                        name = str(item or "").strip()
                        if name in valid_names:
                            primary = name
                            break
                    if primary == "main_chat":
                        telegram_cfg = channels.get("telegram")
                        if isinstance(telegram_cfg, dict):
                            allow_fallback = telegram_cfg.get("allow_fallback")
                            if allow_fallback not in (None, False):
                                errors.append(
                                    "communication.channels.telegram.allow_fallback must be false when main_chat is primary"
                                )

    return len(errors) == 0, errors


def update_config_bulk(updates: dict, user_uuid: Optional[str] = None):
    updates_prepared = copy.deepcopy(updates) if isinstance(updates, dict) else {}
    if not isinstance(updates_prepared, dict):
        updates_prepared = {}

    # Map legacy top-level keys into the system section if provided
    for legacy_key, mapped_path in LEGACY_PATH_MAP.items():
        if legacy_key in updates_prepared:
            section, field = mapped_path.split(".", 1)
            section_dict = updates_prepared.get(section)
            if not isinstance(section_dict, dict):
                section_dict = {}
            if field not in section_dict:
                section_dict[field] = updates_prepared[legacy_key]
            updates_prepared[section] = section_dict
            updates_prepared.pop(legacy_key, None)

    config = get_config(user_uuid=user_uuid)
    updated, failed = _recursive_update(config, updates_prepared)
    save_config(config, user_uuid=user_uuid)

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
    system_updates = (
        updates_prepared.get("system")
        if isinstance(updates_prepared.get("system"), dict)
        else {}
    )
    new_char_name = system_updates.get("char_name")
    # if new_char_name:
    #     database_service.get_or_create_character(new_char_name)

    return updated, failed


def load_generation_presets() -> list:
    if not os.path.exists(PRESETS_PATH):
        return []
    with open_utf8(PRESETS_PATH, "r") as f:
        return json.load(f)


def apply_preset_by_name(preset_name: str, user_uuid: Optional[str] = None) -> bool:
    presets = load_generation_presets()
    matched = next((p for p in presets if p["name"] == preset_name), None)

    if not matched:
        return False

    config = get_config(user_uuid=user_uuid)
    config["generate_settings"] = matched
    save_config(config, user_uuid=user_uuid)
    return True


def get_user_config(user_id: str) -> dict:
    return get_config(user_uuid=user_id)


def save_user_config(user_id: str, config: dict) -> bool:
    try:
        save_config(config, user_uuid=user_id)
        return True
    except Exception:
        return False
