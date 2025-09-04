# ===========================================================
# Module: api_service.py
# Purpose: Generate a request for the model, including system prompt and clearing history
# Used in: ollama_routes (for preparing history)
# Features:
# - Loads a character's YAML profile
# - Removes unnecessary fields from history (e.g. timestamp)
# - Handles native Ollama HTTP errors (context length exceeded, OOM, etc.)
# ===========================================================

import asyncio
import yaml
import os
import threading
import json
from datetime import datetime, timezone

from fastapi import WebSocket

from services import ollama_service, database_service
from services.logger_service import log_audit_entry, AuditStatus
from services.voice_service import (
    speak_line,
    set_speaking,
    stream_speak_line,
    tts_queue,
)
from services.config_service import get_config_value
from services.database_service import get_message_by_id, add_message_to_history
from services.rag_service import retrieve_lore_fragments, format_lore_block
from services.ollama_service import api_stream
from utils.context_builder import build_memory_context
from utils.structure_utils import get_label_from_file
from utils.open_file_w_utf8 import open_utf8

from core.emotion_intent_analyzer import analyze_emotion, generate_instruction


# ===========================================================
# System prompt loader
# ===========================================================
def load_system_prompt() -> str:
    base_path = os.path.join(os.path.dirname(__file__), "..", "config", "characters")
    char_name = get_config_value("char_name", default="default")
    filename = f"{char_name}.yaml"
    full_path = os.path.join(base_path, filename)
    fallback_path = os.path.join(base_path, "default.yaml")

    try:
        if os.path.exists(full_path):
            with open_utf8(full_path, "r") as f:
                data = yaml.safe_load(f)
                return data.get("prompt", "")
        elif os.path.exists(fallback_path):
            with open_utf8(fallback_path, "r") as f:
                data = yaml.safe_load(f)
                return data.get("prompt", "")
        else:
            log_audit_entry(
                event_type="character_prompt_not_found",
                msg=f"[Api Service]: Character prompt not found",
                status=AuditStatus.ERROR,
            )
            return "[System Error] Character prompt not found."
    except Exception as e:
        log_audit_entry(
            event_type="prompt_loading_failed",
            msg=f"[Api Service]: Prompt loading failed",
            status=AuditStatus.ERROR,
            details={"error": str(e)},
        )
        return "[System Error] Prompt loading failed."


# ===========================================================
# Build request
# ===========================================================
def build_chat_request(history, include_system=True):
    sanitized_history = [
        {k: v for k, v in msg.items() if k != "timestamp"} for msg in history
    ]
    if include_system:
        system_prompt = load_system_prompt()
        if system_prompt:
            sanitized_history.insert(0, {"role": "system", "content": system_prompt})
    return sanitized_history


# ===========================================================
# Standard (non-streaming) generation
# ===========================================================
async def run_standard(
    history: list, emit_ws_fn=None, store: bool = True, return_full: bool = False
):
    log_audit_entry(
        event_type="ApiService.RunStandard",
        msg="[Api Service]: Запущена функция генерации",
        status=AuditStatus.INFO,
        details={"inputs": {"history": history}},
    )

    full_history = build_chat_request(history, include_system=False)
    char_name = get_config_value("char_name", "default")
    options = get_generation_options_from_config()
    last_user_message = extract_last_user_message(history)

    # Build system prompt with lore, memory, emotions
    system_prompt = load_system_prompt()
    rag_block, memory_block, emotion_instruction = "", "", ""

    if last_user_message:
        rag_block = format_lore_block(
            retrieve_lore_fragments(last_user_message["content"])
        )
        memory_block = build_memory_context(last_user_message["content"], char_name)
        emotion_instruction = get_emotional_instruction(last_user_message["content"])

    if rag_block:
        system_prompt += f"\n\n{rag_block}"
    if memory_block:
        system_prompt += f"\n\n{memory_block}"
    if emotion_instruction:
        system_prompt += f"\n\n[Emotional reaction]:\n{emotion_instruction}"

    full_history.insert(0, {"role": "system", "content": system_prompt})

    # === Call model ===
    response = ollama_service.api_standard(full_history, options)

    if "error" in response:
        raise RuntimeError(response["error"])

    assistant_content = response.get("message", {}).get("content", "").strip()

    # === Save messages ===
    if last_user_message:
        database_service.add_message_to_history(
            character_name=char_name,
            role="user",
            content=last_user_message["content"],
            timestamp=last_user_message.get("timestamp"),
        )

    new_message_obj = None
    if store:
        new_message_obj = database_service.add_message_to_history(
            character_name=char_name,
            role="assistant",
            content=assistant_content,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )

    # Voice
    if get_config_value("voice.enabled", False):
        set_speaking(True)
        threading.Thread(target=speak_line, args=(assistant_content, False)).start()

    # Logging
    log_audit_entry(
        event_type="generation_standard",
        msg="[API] Generate completed",
        status=AuditStatus.SUCCESS,
        details={
            "user_input": last_user_message["content"] if last_user_message else None,
            "assistant_output": assistant_content,
        },
        meta={"source": "model", "mode": "standard", "full_response": response},
    )

    # WS emit
    if emit_ws_fn and last_user_message:
        await emit_ws_fn(
            {"type": "message", "role": "user", "content": last_user_message["content"]}
        )
        await asyncio.sleep(0.005)
        await emit_ws_fn(
            {"type": "message", "role": "assistant", "content": assistant_content}
        )

    if return_full:
        return {
            "id": new_message_obj.id if new_message_obj else None,
            "content": assistant_content,
            "timestamp": new_message_obj.timestamp if new_message_obj else None,
        }

    return assistant_content


# ===========================================================
# Streaming generation
# ===========================================================
async def run_stream_message(websocket: WebSocket, history: list):
    log_audit_entry(
        event_type="ApiService.RunStream",
        msg="[Api Service]: Start streaming generation",
        status=AuditStatus.INFO,
        details={"inputs": {"history": history}},
    )

    full_history = build_chat_request(history, include_system=False)
    char_name = get_config_value("char_name", "default")
    options = get_generation_options_from_config()
    last_user_message = extract_last_user_message(history)

    system_prompt = load_system_prompt()
    rag_block, memory_block, emotion_instruction = "", "", ""
    if last_user_message:
        rag_block = format_lore_block(
            retrieve_lore_fragments(last_user_message["content"])
        )
        memory_block = build_memory_context(last_user_message["content"], char_name)
        emotion_instruction = get_emotional_instruction(last_user_message["content"])

    if rag_block:
        system_prompt += f"\n\n{rag_block}"
    if memory_block:
        system_prompt += f"\n\n{memory_block}"
    if emotion_instruction:
        system_prompt += f"\n\n[Emotional reaction]:\n{emotion_instruction}"

    full_history.insert(0, {"role": "system", "content": system_prompt})

    # Save user msg и отправляем ack для пользователя
    user_message_obj = None
    if last_user_message:
        user_message_obj = add_message_to_history(
            character_name=char_name,
            role="user",
            content=last_user_message["content"],
            timestamp=normalize_timestamp(last_user_message.get("timestamp")),
        )
        if last_user_message.get("id"):
            await websocket.send_json(
                {
                    "type": "ack_message",
                    "tempId": last_user_message.get("id"),
                    "realId": user_message_obj.id,
                }
            )

    response_chunks = []
    buffer = []
    voice_enabled = get_config_value("voice.enabled", False)
    streaming_tts = get_config_value("voice.streaming_tts", False)

    if voice_enabled:
        set_speaking(True)

    async for chunk in api_stream(full_history, options):
        if not chunk:
            continue
        if "error" in chunk:
            await websocket.send_json({"type": "error", "message": chunk["error"]})
            return

        content = chunk.get("message", {}).get("content", "")
        if isinstance(content, str) and content:
            await websocket.send_json(
                {"type": "message_chunk", "role": "assistant", "content": content}
            )
            response_chunks.append(content)

            if voice_enabled and streaming_tts:
                buffer.append(content)
                buf_text = "".join(buffer)

                # Условие отправки на озвучку
                if len(buf_text) > 50 or buf_text.endswith((".", "!", "?")):
                    devices = []
                    if get_config_value("voice.use_windows_output", True):
                        devices.append(get_config_value("voice.windows_output_id", 0))
                    if get_config_value("voice.use_rvc", False):
                        devices.append(get_config_value("voice.output_id", 0))

                    tts_queue.put((buf_text, devices))
                    buffer = []

    assistant_content = "".join(response_chunks).strip()

    # сохраняем ассистентский ответ
    assistant_message_obj = add_message_to_history(
        character_name=char_name,
        role="assistant",
        content=assistant_content,
        timestamp=datetime.now(timezone.utc),
    )

    # финальное сообщение клиенту
    await websocket.send_json(
        {
            "type": "message",
            "id": assistant_message_obj.id,
            "role": "assistant",
            "content": assistant_content,
        }
    )

    if voice_enabled and not streaming_tts:
        set_speaking(True)
        threading.Thread(target=speak_line, args=(assistant_content, False)).start()

    log_audit_entry(
        event_type="generation_stream",
        msg="[API] Stream generation completed",
        status=AuditStatus.SUCCESS,
        details={
            "user_input": last_user_message["content"] if last_user_message else None,
            "assistant_output": assistant_content,
        },
        meta={"source": "model", "mode": "stream", "full_response": assistant_content},
    )

    await websocket.send_json({"type": "system", "event": "stream_end"})


# ===========================================================
# Utils
# ===========================================================
def normalize_timestamp(ts):
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def get_emotional_instruction(message: str):
    analysis = analyze_emotion(message)
    return generate_instruction(analysis)


def get_generation_options_from_config(exclude: list = None) -> dict:
    exclude = exclude or ["name", "description"]
    full_settings = get_config_value("generate_settings", {})
    return {k: v for k, v in full_settings.items() if k not in exclude}


def extract_last_user_message(history):
    return next((msg for msg in reversed(history) if msg.get("role") == "user"), None)


# ===========================================================
# Initiative generation
# ===========================================================
def run_initiative(emotion: str = "беспокойство"):
    base_prompt = load_system_prompt()

    if emotion == "беспокойство":
        emotion_note = (
            "LIM волнуется из-за долгого молчания пользователя. "
            "Она проявляет инициативу мягко, с заботой и тревожной теплотой.\n\n"
        )
    elif emotion == "раздражение + беспокойство":
        emotion_note = (
            "Пользователь продолжает молчать. LIM ощущает лёгкое раздражение, "
            "но всё ещё заботится.\n\n"
        )
    elif emotion == "обида + злость":
        emotion_note = (
            "LIM чувствует, что пользователь её игнорирует. "
            "Появляется обида и злость.\n\n"
        )
    else:
        emotion_note = "LIM проявляет инициативу, не дождавшись пользователя.\n\n"

    full_prompt = emotion_note + base_prompt
    messages = [{"role": "system", "content": full_prompt}]
    char_name = get_config_value("char_name", "default")
    options = get_generation_options_from_config()

    response = ollama_service.api_standard(messages, options)
    if "error" in response:
        raise RuntimeError(response["error"])

    assistant_content = response.get("message", {}).get("content", "").strip()

    database_service.add_message_to_history(
        character_name=char_name,
        role="assistant",
        content=assistant_content,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )

    if get_config_value("voice.enabled", False):
        set_speaking(True)
        threading.Thread(target=speak_line, args=(assistant_content, False)).start()

    log_audit_entry(
        event_type="generation_initiative",
        msg="[API] Генерация инициативного ответа",
        status=AuditStatus.SUCCESS,
        details={"emotion": emotion, "assistant_output": assistant_content},
        meta={"source": "model", "mode": "initiative", "full_response": response},
    )

    return assistant_content


# ===========================================================
# Playback
# ===========================================================
def play_message(msg_id: str):
    message = get_message_by_id(msg_id)
    if get_config_value("voice.enabled", False):
        set_speaking(True)
        threading.Thread(target=speak_line, args=(message["content"], False)).start()
    return message
