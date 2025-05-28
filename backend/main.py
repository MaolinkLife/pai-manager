# =========================================================
# Модуль: main.py
# Назначение: Точка входа в приложение LIM. Запускает FastAPI, подключает маршруты, активирует CORS
# Используется: при старте всей системы
# Особенности:
# - Подключает конфигурацию (config_service)
# - Включает CORS для связи с фронтом
# - Интегрирует маршруты ollama и config
# - Содержит эндпоинт /api/ping для проверки состояния
# =========================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes.ollama_routes import router as ollama_router
from routes.config_routes import router as config_router
from routes.preset_routes import router as preset_router
from core.initialize import run_startup_checks

run_startup_checks()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # или http://localhost:4200
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ollama_router)
app.include_router(config_router)
app.include_router(preset_router)


@app.get("/api/ping")
def ping():
    return {"message": "pong"}
