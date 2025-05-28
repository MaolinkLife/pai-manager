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

def run_startup_checks():
    """
    Основной метод инициализации LIM.
    Выполняется при старте main.py, до запуска приложения.
    """

    print("[🔧] Запуск инициализации LIM...")
    

    # Проверка наличия и создание конфига
    config_service.ensure_config_exists()

    # Генерация user_id, если он отсутствует
    if not config_service.get_config_value("user_id"):
        user_id = str(uuid.uuid4())
        config_service.set_config_value("user_id", user_id)
        print(f"[🆔] Сгенерирован user_id: {user_id}")
    # else:
    #     print("[✅] user_id уже существует")

    # Создаем базу данных
    database_service.create_database()

    # Можно добавить дополнительные проверки здесь в будущем:
    # - наличие директорий
    # - наличие char_name
    # - структура config.json

    print("[✅] Инициализация завершена успешно.")
