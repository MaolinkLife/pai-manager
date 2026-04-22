# ==========================================================
# Module: initialize.py
# Purpose: Primary initialization of the LIM project before starting FastAPI.
# Responsible for preparing the environment: creating a config, generating user_id,
# checking directories and basic values.
#
# Used in: main.py
# Features:
# - Separates pre-startup checks from the API startup logic
# - Can be called separately as a setup procedure
# =========================================================
import os
import threading
from modules.system.service import (
    ensure_config_exists,
    get_active_character_name,
    get_config_value,
    migrate_owner_config_if_needed,
    migrate_split_settings_if_needed,
)
from constants.paths import MODEL_SUBDIRS
from modules.system.logger import initialize_logger_runtime, log_audit_entry, AuditStatus
from modules.system.localization import get_text
from utils.structure_utils import get_label_from_file


def run_startup_checks():
    """
    The main method for initializing LIM.
    Runs when main.py starts, before the application starts.
    """
    # Local imports prevent cyclic import during bootstrap.
    from modules.database import service as database_service
    from services import preset_service
    from modules.system import character as character_service
    from modules.vision.service import VisionService
    from modules.memory.short_term import ensure_short_term_schema
    from modules.memory.knowledge import ensure_memory_knowledge_schema


    label = get_label_from_file(__file__)
    print(
        get_text(
            "initialize.print_start",
            params={"label": label},
            default="Starting LIM initialization...",
        )
    )
    log_audit_entry(
        event_type="startup_begin",
        msg=get_text(
            "initialize.startup_begin",
            params={"label": label},
            default=f"{label} Starting LIM initialization",
        ),
        status=AuditStatus.SUCCESS,
        message_key="initialize.startup_begin",
        message_args={"label": label},
    )

    # Legacy hook: runtime config is DB-first.
    # Keep startup tolerant for old/partial clean builds where this helper may be absent.
    ensure_config_exists()
    preset_service.ensure_presets_exist()

    initialize_logger_runtime()

    for model_dir in MODEL_SUBDIRS:
        os.makedirs(model_dir, exist_ok=True)

    # Create a database
    database_service.create_database()
    try:
        character_service.import_characters_from_yaml_dir(update_existing=False)
    except Exception as exc:
        log_audit_entry(
            event_type="characters_yaml_sync_failed",
            msg="[Initialize] Failed to sync YAML characters into DB.",
            status=AuditStatus.WARNING,
            details={"error": str(exc)},
        )
    migrate_owner_config_if_needed()
    migrate_split_settings_if_needed()
    ensure_short_term_schema()
    ensure_memory_knowledge_schema()

    char_name = get_active_character_name(default="default_waifu")
    character = None
    if char_name:
        character = character_service.get_or_create_character(char_name)
        log_audit_entry(
            event_type="character_bootstrap",
            msg=get_text(
                "initialize.character_bootstrap",
                params={"char_name": char_name},
                default=f"[Initialize] ensured character '{char_name}' exists",
            ),
            status=AuditStatus.SUCCESS,
            message_key="initialize.character_bootstrap",
            message_args={"char_name": char_name},
        )

    # Additional checks may be added here in the future:
    # - presence of directories
    # - presence of char_name
    # - config.json structure
    vision_enabled = bool(get_config_value("vision.enabled", False))
    if vision_enabled:
        try:
            vision_service = VisionService()
            vision_service.start()
            print(
                get_text(
                    "initialize.print_vision_started",
                    default="[Initialize] Визуальный сервис запущен",
                )
            )
        except Exception as e:
            print(
                get_text(
                    "initialize.print_vision_start_error",
                    params={"error": e},
                    default=f"[Initialize] Ошибка запуска визуального сервиса: {e}",
                )
            )

    print(
        get_text(
            "initialize.print_complete",
            params={"label": label},
            default="Initialization completed successfully.",
        )
    )
    log_audit_entry(
        event_type="startup_complete",
        msg=get_text(
            "initialize.startup_complete",
            params={"label": label},
            default=f"{label} Initialization complete",
        ),
        status=AuditStatus.SUCCESS,
        message_key="initialize.startup_complete",
        message_args={"label": label},
    )


def start_async_warmups() -> None:
    thread = threading.Thread(
        target=_run_short_memory_refresh_warmup,
        name="short-memory-startup-warmup",
        daemon=True,
    )
    thread.start()


def _run_short_memory_refresh_warmup() -> None:
    try:
        from modules.system import character as character_service
        from modules.memory.short_term import refresh_recent_days

        char_name = get_active_character_name(default="default_waifu")
        if not char_name:
            return
        character = character_service.get_or_create_character(char_name)
        log_audit_entry(
            event_type="short_memory_refresh_background_start",
            msg="[Initialize] Starting background short-term memory refresh.",
            status=AuditStatus.INFO,
            details={"character_id": character.id, "character_name": char_name},
        )
        refresh_recent_days(character.id)
        log_audit_entry(
            event_type="short_memory_refresh_background_complete",
            msg="[Initialize] Background short-term memory refresh complete.",
            status=AuditStatus.SUCCESS,
            details={"character_id": character.id, "character_name": char_name},
        )
    except Exception as exc:
        log_audit_entry(
            event_type="short_memory_refresh_failed",
            msg=get_text(
                "initialize.short_memory_refresh_failed",
                default="[Initialize] Не удалось обновить short-term память на старте. Продолжаем запуск.",
            ),
            status=AuditStatus.WARNING,
            details={"error": str(exc)},
            message_key="initialize.short_memory_refresh_failed",
            message_args={"error": str(exc), "character_id": ""},
        )


def shutdown_services():
    """Shut down all services."""
    # ... other shutdown routines ...

    # Stop the vision service
    try:
        from modules.vision.service import VisionService
        vision_service = VisionService()
        vision_service.stop()
        print(
            get_text(
                "initialize.print_vision_stopped",
                default="[Initialize] Визуальный сервис остановлен",
            )
        )
    except Exception as e:
        print(
            get_text(
                "initialize.print_vision_stop_error",
                params={"error": e},
                default=f"[Initialize] Ошибка остановки визуального сервиса: {e}",
            )
        )

