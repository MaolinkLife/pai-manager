# ==========================================================
# Module: initialize.py
# Purpose: Primary initialization of the PAI project before starting FastAPI.
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
from modules.system.logger import (
    initialize_logger_runtime,
    log_audit_entry,
    AuditStatus,
    log_console,
)
from modules.system.localization import get_text
from utils.structure_utils import get_label_from_file


def run_startup_checks():
    """
    The main method for initializing PAI.
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
    log_console("Startup", "Запускаем системную инициализацию.", {"label": label})
    print(
        get_text(
            "initialize.print_start",
            params={"label": label},
            default="Starting PAI initialization...",
        )
    )
    log_audit_entry(
        event_type="startup_begin",
        msg=get_text(
            "initialize.startup_begin",
            params={"label": label},
            default=f"{label} Starting PAI initialization",
        ),
        status=AuditStatus.SUCCESS,
        message_key="initialize.startup_begin",
        message_args={"label": label},
    )

    # Legacy hook: runtime config is DB-first.
    # Keep startup tolerant for old/partial clean builds where this helper may be absent.
    log_console("Startup", "Проверяем конфигурационное хранилище.")
    ensure_config_exists()
    log_console("Startup", "Проверяем настройки генерации по умолчанию.")
    preset_service.ensure_presets_exist()

    log_console("Startup", "Инициализируем runtime-логи.")
    initialize_logger_runtime()

    log_console("Startup", "Проверяем системные директории моделей.")
    for model_dir in MODEL_SUBDIRS:
        os.makedirs(model_dir, exist_ok=True)

    log_console("Startup", "Переходим к подготовке базы данных.")
    database_service.create_database()
    log_console("Startup", "Синхронизируем персонажей из YAML.")
    try:
        character_service.import_characters_from_yaml_dir(update_existing=False)
        log_console("Startup", "Синхронизация персонажей завершена.")
    except Exception as exc:
        log_console("Startup", "Синхронизация персонажей завершилась ошибкой.", {"error": str(exc)})
        log_audit_entry(
            event_type="characters_yaml_sync_failed",
            msg="[Initialize] Failed to sync YAML characters into DB.",
            status=AuditStatus.WARNING,
            details={"error": str(exc)},
        )
    log_console("Startup", "Проверяем конфигурацию владельца.")
    owner_migrated = migrate_owner_config_if_needed()
    if owner_migrated:
        log_console("Startup", "Конфигурационный файл владельца создан.")
    else:
        log_console("Startup", "Конфигурация владельца не требует миграции.")

    log_console("Startup", "Проверяем разделенные настройки voice/vision.")
    split_migrated = migrate_split_settings_if_needed()
    if split_migrated:
        log_console("Startup", "Разделенные настройки синхронизированы.", {"users": split_migrated})
    else:
        log_console("Startup", "Разделенные настройки уже актуальны.")

    log_console("Startup", "Синхронизируем short-term память.")
    ensure_short_term_schema()
    log_console("Startup", "Синхронизируем knowledge-память.")
    ensure_memory_knowledge_schema()

    char_name = get_active_character_name(default="default_waifu")
    character = None
    if char_name:
        log_console("Startup", "Проверяем активного персонажа.", {"character": char_name})
        character = character_service.get_or_create_character(char_name)
        log_console("Startup", "Активный персонаж готов.", {"character": char_name, "id": character.id})
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
            log_console("Startup", "Запускаем визуальный сервис.")
            vision_service = VisionService()
            vision_service.start()
            print(
                get_text(
                    "initialize.print_vision_started",
                    default="[Initialize] Визуальный сервис запущен",
                )
            )
        except Exception as e:
            log_console("Startup", "Визуальный сервис не запущен.", {"error": str(e)})
            print(
                get_text(
                    "initialize.print_vision_start_error",
                    params={"error": e},
                    default=f"[Initialize] Ошибка запуска визуального сервиса: {e}",
                )
            )

    log_console("Startup", "Настройки созданы, backend готов к запуску WebUI.")
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
    enabled = bool(get_config_value("memory.short_term.startup_refresh_enabled", False))
    env_enabled = str(os.getenv("STARTUP_SHORT_MEMORY_REFRESH", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled and not env_enabled:
        log_audit_entry(
            event_type="short_memory_refresh_background_skipped",
            msg="[Initialize] Background short-term memory refresh skipped on startup.",
            status=AuditStatus.INFO,
            details={"reason": "disabled"},
        )
        return

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
    """Shut down all services.

    Called from main.app_shutdown. Designed to be robust: each step is wrapped
    in its own try/except so a failure in one subsystem cannot leave the rest
    holding GPU memory or file handles.
    """

    # Release generation providers — even max_speed / release_after_use=False
    # profiles must let go of weights at shutdown.
    try:
        from modules.generative.manager import generation_manager
        from modules.system.logger import log_audit_entry, AuditStatus

        for name, provider in generation_manager._providers.items():
            try:
                provider.release_resources()
            except Exception as exc:
                log_audit_entry(
                    event_type="shutdown_generative_release_error",
                    msg="[Initialize] Не удалось освободить ресурсы генеративного провайдера на shutdown.",
                    status=AuditStatus.WARNING,
                    details={"provider": name, "error": str(exc)},
                )
        print("[Initialize] Генеративные провайдеры выгружены.")
    except Exception as exc:
        print(f"[Initialize] Ошибка выгрузки генеративных провайдеров: {exc}")

    # Shut down the TTS subsystem (releases XTTS/RVC weights, stops worker threads).
    try:
        from modules.tts import service as tts_service

        tts_service.shutdown()
        print("[Initialize] TTS сервис остановлен.")
    except Exception as exc:
        print(f"[Initialize] Ошибка остановки TTS сервиса: {exc}")

    # Stop the vision service.
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

