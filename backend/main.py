# ==========================================================
# Module: main.py
# Purpose: Entry point to the LIM application. Launches FastAPI, connects routes, activates CORS
# Used: at startup of the entire system
# Features:
# - Connects configuration (config_service)
# - Enables CORS for communication with the front
# - Integrates ollama and config routes
# - Contains the /api/ping endpoint for checking the status
# =======================================================

import asyncio
import os
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.initialize import run_startup_checks, start_async_warmups
from modules.system.logger import log_error, log_traceback

# Windows: ProactorEventLoop may emit noisy ConnectionResetError traces
# on abrupt client disconnects (WinError 10054). Selector loop is more stable
# for this backend/websocket workload.
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

# Запускаем инициализацию ДО импортов маршрутов
try:
    run_startup_checks()
except Exception as exc:
    log_traceback(exc, source="startup")
    log_error(
        error_msg=f"Startup checks failed: {exc}",
        context={"traceback": traceback.format_exc()},
        severity="critical",
    )
    raise

# Теперь можно импортировать маршруты, т.к. конфиг уже инициализирован
from routes.ollama_routes import router as ollama_router
from routes.config_routes import router as config_router
from routes.preset_routes import router as preset_router
from routes.logger_routes import router as logger_router
from routes.voice_routes import router as voice_router
from routes.lorebook_routes import router as lorebook_router
from routes.resources_routes import router as resources_router
from routes.ws_routes import ws_router
from routes.embed_routes import router as embed_router
from routes.vector_routes import router as vector_router
from routes.storage_routes import router as storage_router
from routes.memory_routes import router as memory_router
from routes.moral_routes import router as moral_router
from routes.auth_routes import router as auth_router
from routes.tunnel_routes import router as tunnel_router
from routes.telegram_routes import router as telegram_router
from routes.synthesis_routes import router as synthesis_router

from loops.loop_core import run_loop
from modules.system import tunnel as tunnel_service
from modules.telegram.runtime import autostart_telegram_bridge, stop_telegram_bridge

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # or http://localhost:4200
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ollama_router)
app.include_router(config_router)
app.include_router(preset_router)
app.include_router(logger_router)
app.include_router(voice_router)
app.include_router(resources_router)
app.include_router(ws_router)
app.include_router(lorebook_router)
app.include_router(embed_router)
app.include_router(vector_router)
app.include_router(storage_router)
app.include_router(memory_router)
app.include_router(moral_router)
app.include_router(auth_router)
app.include_router(tunnel_router)
app.include_router(telegram_router)
app.include_router(synthesis_router)

# Start background loops
run_loop()


@app.on_event("startup")
def app_startup() -> None:
    start_async_warmups()
    tunnel_service.autostart_owner_tunnel()
    autostart_telegram_bridge()


@app.on_event("shutdown")
def app_shutdown() -> None:
    stop_telegram_bridge()
    tunnel_service.stop_tunnel()


@app.get("/api/ping")
def ping():
    return {"message": "pong"}
