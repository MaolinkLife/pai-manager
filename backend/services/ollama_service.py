# ===========================================================
# Module: ollama_service.py
# Purpose: Interaction with Ollama model (text and visual)
# Used in: ollama_routes
# Features:
# - Supports both regular and streaming output
# - Processes visual models separately
# =========================================================

import asyncio
from ollama import chat, ChatResponse
from ollama._types import ResponseError
from ollama import list as ollama_list

from requests.exceptions import ConnectionError as RequestsConnectionError

from services.config_service import get_config_value
from services.logger_service import log_audit_entry, log_error, AuditStatus

from functools import partial

ollama_model_visual = get_config_value("api.visual_model")

# Returns a dictionary of temperature parameters at the selected level (0-2).
# TODO: Probably won't be needed anymore
def get_temperature_options(
    temp_level: int, stop: list | None, max_tokens: int
) -> dict | None:
    if temp_level == -1:
        return None

    if temp_level == 0:
        return {
            "temperature": 1.17,
            "min_p": 0.0597,
            "top_p": 0.87,
            "top_k": 64,
            "repeat_penalty": 1.09,
            "stop": stop,
            "num_predict": max_tokens,
        }

    if temp_level == 1:
        return {
            "temperature": 1.27,
            "min_p": 0.0497,
            "top_p": 0.87,
            "top_k": 72,
            "repeat_penalty": 1.12,
            "stop": stop,
            "num_predict": max_tokens,
        }

    if temp_level == 2:
        return {
            "temperature": 1.47,
            "min_p": 0.0397,
            "top_p": 0.97,
            "top_k": 99,
            "repeat_penalty": 1.19,
            "stop": stop,
            "num_predict": max_tokens,
        }


# Sends a regular (non-streaming) chat request to Ollama, returns a response.
def api_standard(history, options: dict):
    ollama_model=get_config_value("api.model")
    try:
        response: ChatResponse = chat(
            model=ollama_model,
            messages=history,
            keep_alive="25h",
            options=options,
        )
        return response

    except ResponseError as e:
        log_audit_entry(
            event_type="generate_message", 
            msg=f"[Ollama] Model '{ollama_model}' not found or not loaded",
            status=AuditStatus.ERROR,
            details={
                "context": f"Ollama ResponseError: {e}",
                "status": "error"
            }
        )
        
        log_error(
            f"Ollama ResponseError: {e}\nModel '{ollama_model}' not found or not loaded."
        )
        
        return f"[ERROR] Model '{ollama_model}' not found. Check configuration or upload model manually."


# Sends a request with stream=True - generates a text stream.
async def api_stream(history: list, options: dict):
    ollama_model = get_config_value("api.model")

    try:
        loop = asyncio.get_running_loop()
        sync_generator = await loop.run_in_executor(
            None,
            partial(chat, model=ollama_model, messages=history, stream=True, keep_alive="25h", options=options)
        )

        for chunk in sync_generator:
            yield chunk

    except ResponseError as e:
        log_error(f"Ollama ResponseError: {e}")
    except Exception as e:
        log_error(f"Unknown error in stream: {e}")


# Query the visual model.
def api_standard_image(history):
    try:
        response: ChatResponse = chat(
            model=get_config_value("api.visual_model"),
            messages=history,
            keep_alive="25h",
        )
        return response.message.content

    except ResponseError as e:
        log_error(f"Vision-model '{ollama_model_visual}' not found: {e}")
        return "[ERROR] The visual model is not loaded."


# Stream generation with visual model.
def api_stream_image(history):
    try:
        return chat(
            model=ollama_model_visual,
            messages=history,
            stream=True,
            keep_alive="25h",
        )
    except ResponseError as e:
        log_error(f"Ollama ResponseError: {e}")
        return None
    except Exception as e:
        log_error(f"Unknown error in stream: {e}")
        return None


def is_ollama_available() -> bool:
    try:
        ollama_list()
        return True
    except (ResponseError, RequestsConnectionError, ConnectionError):
        return False
    except Exception as e:
        print(f"[ERROR] Error while checking Ollama: {e}")
        return False


# Returns a list of available models if Ollama is running. Otherwise, an error message
def get_models():
    if not is_ollama_available():
        return {
            "status": "error",
            "message": "Ollama not installed, not running or not accessible",
        }

    try:
        models = ollama_list()
        model_list = models.models  # this is not a dict, but an attribute

        return {
            "status": "ok",
            "models": [m.model for m in model_list],  # access to an object field
        }

    except ResponseError as e:
        return {"status": "error", "message": f"Ollama returned an error: {str(e)}"}

    except Exception as e:
        import traceback

        traceback.print_exc()

        return {
            "status": "error",
            "message": f"Unknown error while getting models: {str(e)}",
        }
