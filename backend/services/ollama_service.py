# ===========================================================
# Module: ollama_service.py
# Purpose: Interaction with Ollama model (text and visual)
# Used in: ollama_routes
# Features:
# - Direct HTTP calls to Ollama API
# - Full error transparency (native Ollama errors are returned)
# ===========================================================

import requests
import aiohttp
import asyncio
import json

from requests.exceptions import ConnectionError as RequestsConnectionError

from services.config_service import get_config_value
from services.logger_service import log_audit_entry, log_error, AuditStatus


OLLAMA_API_URL = "http://localhost:11434/api"


def get_ollama_visual_model():
    """Получить модель визуального анализа"""
    return get_config_value("api.visual_model")


# ===========================================================
# Regular chat (non-streaming)
# ===========================================================
def api_standard(history, options: dict):
    ollama_model = get_config_value("api.model")
    try:
        r = requests.post(
            f"{OLLAMA_API_URL}/chat",
            json={
                "model": ollama_model,
                "messages": history,
                "options": options,
                "stream": False,
            },
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            log_audit_entry(
                event_type="ollama_error",
                msg=f"[Ollama] Error: {data['error']}",
                status=AuditStatus.ERROR,
                details={"model": ollama_model, "error": data["error"]},
            )
            raise RuntimeError(data["error"])

        return data

    except Exception as e:
        log_error(f"[Ollama] HTTP error: {e}")
        raise


# ===========================================================
# Streaming chat
# ===========================================================
async def api_stream(history: list, options: dict):
    ollama_model = get_config_value("api.model")
    url = f"{OLLAMA_API_URL}/chat"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={
                "model": ollama_model,
                "messages": history,
                "options": options,
                "stream": True,
            },
        ) as resp:
            async for line in resp.content:
                if not line.strip():
                    continue
                try:
                    data = line.decode("utf-8").strip()
                    obj = json.loads(data)
                    if "error" in obj:
                        yield {"error": obj["error"]}
                        return
                    yield obj
                except Exception as e:
                    log_error(f"[Ollama stream parse error]: {e}")


# ===========================================================
# Visual model: regular
# ===========================================================
def api_standard_image(history):
    ollama_model_visual = (
        get_ollama_visual_model()
    )  # Получаем модель при вызове функции
    try:
        r = requests.post(
            f"{OLLAMA_API_URL}/chat",
            json={
                "model": ollama_model_visual,
                "messages": history,
                "stream": False,
            },
            timeout=300,
        )
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            log_error(f"[Ollama visual error]: {data['error']}")
            return f"[ERROR] {data['error']}"

        return data.get("message", {}).get("content", "")

    except Exception as e:
        log_error(f"[Ollama visual HTTP error]: {e}")
        return "[ERROR] Visual model request failed."


# ===========================================================
# Visual model: streaming
# ===========================================================
async def api_stream_image(history):
    ollama_model_visual = (
        get_ollama_visual_model()
    )  # Получаем модель при вызове функции
    url = f"{OLLAMA_API_URL}/chat"

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={
                "model": ollama_model_visual,
                "messages": history,
                "stream": True,
            },
        ) as resp:
            async for line in resp.content:
                if not line.strip():
                    continue
                try:
                    data = line.decode("utf-8").strip()
                    obj = json.loads(data)
                    if "error" in obj:
                        yield {"error": obj["error"]}
                        return
                    yield obj
                except Exception as e:
                    log_error(f"[Ollama visual stream parse error]: {e}")
                    return


# ===========================================================
# Check if Ollama is alive
# ===========================================================
def is_ollama_available() -> bool:
    try:
        r = requests.get(f"{OLLAMA_API_URL}/tags", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


# ===========================================================
# Get list of models
# ===========================================================
def get_models():
    if not is_ollama_available():
        return {
            "status": "error",
            "message": "Ollama not installed, not running or not accessible",
        }

    try:
        r = requests.get(f"{OLLAMA_API_URL}/tags", timeout=10)
        r.raise_for_status()
        data = r.json()
        models = [m["name"] for m in data.get("models", [])]
        return {"status": "ok", "models": models}
    except Exception as e:
        return {"status": "error", "message": f"Ollama error: {str(e)}"}
