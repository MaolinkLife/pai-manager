# =========================================================
# Модуль: initialize.py
# Назначение: Первичная инициализация проекта LIM перед запуском FastAPI.
# Отвечает за подготовку окружения: создание конфига, генерацию user_id,
# проверку директорий и базовых значений.
#
# Используется в: main.py
# Особенности:
# - Отделяет pre-startup проверки от логики запуска API
# - Может быть вызван отдельно как setup-процедура
# =========================================================

import uuid
import os

from services import config_service
from services import database_service
from services import preset_service

from services.logger_service import initialize_log_files, log_audit, log_audit_entry, AuditStatus

from utils.structure_utils import get_label_from_file

def run_startup_checks():
    """
    Основной метод инициализации LIM.
    Выполняется при старте main.py, до запуска приложения.
    """

    print("[🔧] Запуск инициализации LIM...")
    log_audit_entry(
        event_type="startup_begin", 
        msg=f"{get_label_from_file(__file__)} Запуск инициализации LIM", 
        status=AuditStatus.SUCCESS
    )
    # log_audit("startup_begin", {"msg": "[CORE] Запуск инициализации LIM", "status": "Success"})

    # Проверка наличия и создание конфига
    config_service.ensure_config_exists()
    # log_audit("config_checked", {"status": "OK", "msg": "[CONFIG SERIVCE]"})
    
    preset_service.ensure_presets_exist()
    # log_audit("presets_checked", {"status": "OK"})
    
    
    initialize_log_files()
    # log_audit("log_initialized", {"msg": "Файлы логов инициализированы"})

    # Генерация user_id, если он отсутствует
    if not config_service.get_config_value("user_id"):
        user_id = str(uuid.uuid4())
        config_service.set_config_value("user_id", user_id)
        print(f"[🆔] Сгенерирован user_id: {user_id}")
        log_audit("user_id_generated", {"user_id": user_id})
    # else:
    #     print("[✅] user_id уже существует")
    #     log_audit("user_id_exists", {"msg": "user_id уже существует"})

    # Создаем базу данных
    database_service.create_database()
    # log_audit("database_created", {"status": "OK"})

    # Можно добавить дополнительные проверки здесь в будущем:
    # - наличие директорий
    # - наличие char_name
    # - структура config.json

    print("[✅] Инициализация завершена успешно.")
    # log_audit("startup_complete", {"msg": "Инициализация завершена"})
    log_audit_entry(
        event_type="startup_complete", 
        msg=f"{get_label_from_file(__file__)} Инициализация завершена", 
        status=AuditStatus.SUCCESS
    )
