# ==========================================================
# Module: main.py
# Purpose: Entry point to the PAI application. Launches FastAPI, connects routes, activates CORS
# Used: at startup of the entire system
# Features:
# - Connects configuration (config_service)
# - Enables CORS for communication with the front
# - Integrates ollama and config routes
# - Contains the /api/ping endpoint for checking the status
# =======================================================

import asyncio
import os
import time
import traceback

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.initialize import run_startup_checks, shutdown_services, start_async_warmups
from core import access_guard
from modules.system.logger import log_console, log_error, log_traceback

# Windows: ProactorEventLoop may emit noisy ConnectionResetError traces
# on abrupt client disconnects (WinError 10054). Selector loop is more stable
# for this backend/websocket workload.
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass


def _is_windows_connection_reset(exc: BaseException | None) -> bool:
    return (
        os.name == "nt"
        and isinstance(exc, ConnectionResetError)
        and getattr(exc, "winerror", None) == 10054
    )


def _install_asyncio_exception_filter() -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    previous_handler = loop.get_exception_handler()

    def _handler(current_loop, context):
        exc = context.get("exception")
        if _is_windows_connection_reset(exc):
            return
        if previous_handler:
            previous_handler(current_loop, context)
            return
        current_loop.default_exception_handler(context)

    loop.set_exception_handler(_handler)

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
from routes.sandbox_routes import router as sandbox_router
from routes.web_runtime_routes import router as web_runtime_router
from routes.debug_vault_routes import router as debug_vault_router
from routes.self_watcher_routes import router as self_watcher_router

from loops.loop_core import run_loop
from modules.system import tunnel as tunnel_service
from modules.telegram.runtime import autostart_telegram_bridge, stop_telegram_bridge

app = FastAPI()


# NOTE: FastAPI middleware decorators are LIFO — the last decorator declared
# becomes the *outermost* middleware. We want order (outer → inner):
#   CORSMiddleware → console_api_request_logger → api_access_guard → app
# so logging captures every request including 403s emitted by the guard.
# That means: declare api_access_guard FIRST, console_api_request_logger SECOND.


@app.middleware("http")
async def api_access_guard(request, call_next):
    # /api/ping stays open so health checks and the launcher keep working,
    # everything else is gated by core.access_guard policy.
    if request.url.path != "/api/ping":
        try:
            access_guard.enforce_http(request)
        except Exception as exc:
            from fastapi.responses import JSONResponse

            status_code = getattr(exc, "status_code", 500)
            detail = getattr(exc, "detail", "Forbidden")
            return JSONResponse(status_code=status_code, content={"detail": detail})
    return await call_next(request)


@app.middleware("http")
async def console_api_request_logger(request, call_next):
    started = time.perf_counter()
    path = request.url.path
    should_log = path.startswith("/api") and path != "/api/ping"
    if should_log:
        log_console("API", "Запрос получен.", {"method": request.method, "path": path})
    try:
        response = await call_next(request)
    except Exception as exc:
        if should_log:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
            log_console(
                "API",
                "Запрос завершился ошибкой.",
                {
                    "method": request.method,
                    "path": path,
                    "elapsed_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
        raise
    if should_log:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        log_console(
            "API",
            "Запрос обработан.",
            {
                "method": request.method,
                "path": path,
                "status": response.status_code,
                "elapsed_ms": elapsed_ms,
            },
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # access guard performs the actual host/origin policy check
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
app.include_router(sandbox_router)
app.include_router(web_runtime_router)
app.include_router(debug_vault_router)
app.include_router(self_watcher_router)

# Start background loops
run_loop()


@app.on_event("startup")
def app_startup() -> None:
    _install_asyncio_exception_filter()
    start_async_warmups()
    tunnel_service.autostart_owner_tunnel()
    autostart_telegram_bridge()


@app.on_event("shutdown")
def app_shutdown() -> None:
    # Stop external bridges first so they cannot send during teardown,
    # then release model/runtime resources.
    try:
        stop_telegram_bridge()
    except Exception as exc:
        log_console("Shutdown", "Не удалось остановить Telegram bridge.", {"error": str(exc)})
    try:
        tunnel_service.stop_tunnel()
    except Exception as exc:
        log_console("Shutdown", "Не удалось остановить tunnel.", {"error": str(exc)})
    try:
        shutdown_services()
    except Exception as exc:
        log_console("Shutdown", "Ошибка в shutdown_services.", {"error": str(exc)})


@app.get("/api/ping")
def ping():
    return {"message": "pong"}
