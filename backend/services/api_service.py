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
import gc
import torch
import re
from datetime import datetime
from services.config_service import get_config_value
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect
from typing import Callable, Awaitable
from datetime import datetime, timezone
from services import ollama_service, database_service
from services.logger_service import log_audit_entry, AuditStatus
from services.voice_service import (
    speak_line,
    set_speaking,
    stream_speak_line,
    tts_queue,
)
from services.voice_state import VoiceStage, voice_state
from services.config_service import get_config_value
from services.database_service import get_message_by_id, add_message_to_history
from services.rag_service import retrieve_lore_fragments, format_lore_block
from services.ollama_service import api_stream
from utils.context_builder import build_memory_context
from utils.structure_utils import get_label_from_file
from utils.open_file_w_utf8 import open_utf8
from core.emotion_intent_analyzer import analyze_emotion, generate_instruction


THINK_PATTERN = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)


def split_reasoning(raw: str) -> tuple[str, str]:
    if not raw:
        return "", ""

    match = THINK_PATTERN.search(raw)
    if not match:
        return raw.strip(), ""

    reasoning = match.group(1).strip()
    cleaned = THINK_PATTERN.sub("", raw).strip()
    return cleaned, reasoning


def strip_reasoning_from_chunk(chunk: str, in_reasoning: bool) -> tuple[str, str, bool]:
    if not chunk:
        return "", "", in_reasoning

    speech_parts: list[str] = []
    reasoning_parts: list[str] = []
    lower_chunk = chunk.lower()
    idx = 0
    while idx < len(chunk):
        if in_reasoning:
            end_idx = lower_chunk.find("</think>", idx)
            if end_idx == -1:
                reasoning_parts.append(chunk[idx:])
                return "".join(speech_parts), "".join(reasoning_parts), True
            reasoning_parts.append(chunk[idx:end_idx])
            idx = end_idx + len("</think>")
            in_reasoning = False
        else:
            start_idx = lower_chunk.find("<think>", idx)
            if start_idx == -1:
                speech_parts.append(chunk[idx:])
                break
            speech_parts.append(chunk[idx:start_idx])
            idx = start_idx + len("<think>")
            in_reasoning = True

    return "".join(speech_parts), "".join(reasoning_parts), in_reasoning


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
    """
    System prompt is already embedded in history; we only strip timestamps.
    """
    sanitized_history = [
        {k: v for k, v in msg.items() if k != "timestamp"} for msg in history
    ]
    # Do not append system prompt here; it already exists in history
    return sanitized_history


# ===========================================================
# Standard (non-streaming) generation
# ===========================================================
async def run_standard(
    history: list, emit_ws_fn=None, store: bool = True, return_full: bool = False
):
    log_audit_entry(
        event_type="ApiService.RunStandard",
        msg="[Api Service]: Generation function started",
        status=AuditStatus.INFO,
        details={"inputs": {"history": history}},
    )

    full_history = build_chat_request(history, include_system=False)
    char_name = get_config_value("char_name", "default")
    options = get_generation_options_from_config()
    last_user_message = extract_last_user_message(history)

    # Build system prompt with lore, memory, emotions
    system_prompt = None
    for msg in history:
        if msg.get("role") == "system":
            system_prompt = msg.get("content")
            break

    # Fallback to the default system prompt if none was supplied
    if not system_prompt:
        base_system_prompt = load_system_prompt()
        system_prompt = base_system_prompt
        # Only append RAG, memory, and emotion blocks when using the fallback
        if last_user_message:
            rag_block = format_lore_block(
                retrieve_lore_fragments(last_user_message["content"])
            )
            # Use MemoryLayer to obtain context
            from core.memory_layer import MemoryLayer

            memory_layer = MemoryLayer()
            # Use await instead of asyncio.run because we are already inside an async function
            memory_context = await memory_layer.get_context(last_user_message)
            memory_block = memory_context.get("recent_conversation", "")

            emotion_instruction = get_emotional_instruction(
                last_user_message["content"]
            )
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

    assistant_raw = response.get("message", {}).get("content", "").strip()
    assistant_content, assistant_reasoning = split_reasoning(assistant_raw)

    # === Save messages ===
    if last_user_message:
        database_service.add_message_to_history(
            character_name=char_name,
            role="user",
            content=last_user_message["content"],
            timestamp=last_user_message.get("timestamp"),
        )

    new_message_obj = None
    if store and assistant_content:
        new_message_obj = database_service.add_message_to_history(
            character_name=char_name,
            role="assistant",
            content=assistant_content,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        )
        if assistant_reasoning:
            database_service.add_reasoning_entry(
                new_message_obj.id,
                assistant_reasoning,
            )

    # Voice
    if get_config_value("voice.enabled", False) and assistant_content:
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
            "assistant_reasoning": assistant_reasoning,
        },
        meta={
            "source": "model",
            "mode": "standard",
            "full_response": response,
            "assistant_raw": assistant_raw,
        },
    )

    # WS emit
    if emit_ws_fn and last_user_message:
        await emit_ws_fn(
            {"type": "message", "role": "user", "content": last_user_message["content"]}
        )
        await asyncio.sleep(0.005)
        if assistant_content:
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
async def run_stream_message(
    websocket: WebSocket | None,
    history: list,
    send_fn: Callable[[dict], Awaitable[bool]] | None = None,
):
    async def safe_send(payload: dict) -> bool:
        if send_fn is not None:
            try:
                await send_fn(payload)
                return True
            except Exception:
                return False
        if websocket is not None:
            try:
                await websocket.send_json(payload)
                return True
            except (WebSocketDisconnect, RuntimeError):
                return False
        return False

    log_audit_entry(
        event_type="ApiService.RunStream",
        msg="[Api Service]: Start streaming generation",
        status=AuditStatus.INFO,
        details={"inputs": {"history": history}},
    )

    await safe_send({"type": "system", "event": "typing_start"})

    try:
        full_history = build_chat_request(history, include_system=False)
        char_name = get_config_value("char_name", "default")
        options = get_generation_options_from_config()
        last_user_message = extract_last_user_message(history)

        # Extract system prompt from history or build a fallback
        system_prompt = None
        for msg in history:
            if msg.get("role") == "system":
                system_prompt = msg.get("content")
                break

        # Fallback to the default system prompt if none was supplied
        if not system_prompt:
            base_system_prompt = load_system_prompt()
            system_prompt = base_system_prompt
            # Only append RAG, memory, and emotion blocks when using the fallback
            if last_user_message:
                rag_block = format_lore_block(
                    retrieve_lore_fragments(last_user_message["content"])
                )
                memory_block = build_memory_context(
                    last_user_message["content"], char_name
                )
                emotion_instruction = get_emotional_instruction(
                    last_user_message["content"]
                )

                if rag_block:
                    system_prompt += f"\n\n{rag_block}"
                if memory_block:
                    system_prompt += f"\n\n{memory_block}"
                if emotion_instruction:
                    system_prompt += f"\n\n[Emotional reaction]:\n{emotion_instruction}"

        # Insert system prompt at the beginning of the history
        full_history.insert(0, {"role": "system", "content": system_prompt})

        # Save the user message and send ack back to the client
        user_message_obj = None
        if last_user_message:
            user_message_obj = add_message_to_history(
                character_name=char_name,
                role="user",
                content=last_user_message["content"],
                timestamp=normalize_timestamp(last_user_message.get("timestamp")),
            )
            if last_user_message.get("id"):
                if not await safe_send(
                    {
                        "type": "ack_message",
                        "tempId": last_user_message.get("id"),
                        "realId": user_message_obj.id,
                    }
                ):
                    return

        raw_chunks: list[str] = []
        buffer: list[str] = []
        streaming_in_reasoning = False
        voice_enabled = get_config_value("voice.enabled", False)
        streaming_tts = get_config_value("voice.streaming_tts", False)

        speech_started = False

        async for chunk in api_stream(full_history, options):
            if not chunk:
                continue
            if "error" in chunk:
                await safe_send({"type": "error", "message": chunk["error"]})
                return

            content = chunk.get("message", {}).get("content", "")
            if isinstance(content, str) and content:
                if not await safe_send(
                    {"type": "message_chunk", "role": "assistant", "content": content}
                ):
                    return
                raw_chunks.append(content)

                speech_chunk, _, streaming_in_reasoning = strip_reasoning_from_chunk(
                    content, streaming_in_reasoning
                )

                if voice_enabled and streaming_tts and speech_chunk:
                    if not speech_started and voice_state.stage() == VoiceStage.WAITING:
                        voice_state.enter_listening("generation_complete_stream")
                    if not speech_started:
                        set_speaking(True)
                        speech_started = True
                    buffer.append(speech_chunk)
                    buf_text = "".join(buffer)

                    if len(buf_text) > 50 or buf_text.endswith((".", "!", "?")):
                        devices = []
                        if get_config_value("voice.use_windows_output", True):
                            devices.append(
                                get_config_value("voice.windows_output_id", 0)
                            )
                        if get_config_value("voice.use_rvc", False):
                            devices.append(get_config_value("voice.output_id", 0))

                        tts_queue.put((buf_text, devices))
                        buffer = []

        if voice_enabled and streaming_tts and buffer:
            if not speech_started and voice_state.stage() == VoiceStage.WAITING:
                voice_state.enter_listening("generation_complete_stream")
            if not speech_started:
                set_speaking(True)
                speech_started = True
            buf_text = "".join(buffer)
            if buf_text:
                devices = []
                if get_config_value("voice.use_windows_output", True):
                    devices.append(get_config_value("voice.windows_output_id", 0))
                if get_config_value("voice.use_rvc", False):
                    devices.append(get_config_value("voice.output_id", 0))
                tts_queue.put((buf_text, devices))
            buffer = []

        assistant_raw = "".join(raw_chunks).strip()
        assistant_content, assistant_reasoning = split_reasoning(assistant_raw)

        # Persist the assistant response
        assistant_message_obj = None
        if assistant_content:
            assistant_message_obj = add_message_to_history(
                character_name=char_name,
                role="assistant",
                content=assistant_content,
                timestamp=datetime.now(timezone.utc),
            )
            if assistant_reasoning:
                database_service.add_reasoning_entry(
                    assistant_message_obj.id,
                    assistant_reasoning,
                )

        # Final message pushed to the client
        await safe_send(
            {
                "type": "message",
                "id": assistant_message_obj.id if assistant_message_obj else None,
                "role": "assistant",
                "content": assistant_raw,
            }
        )

        if voice_state.stage() == VoiceStage.WAITING:
            voice_state.enter_listening("generation_complete")

        if voice_enabled and not streaming_tts and assistant_content:
            set_speaking(True)
            threading.Thread(target=speak_line, args=(assistant_content, False)).start()

        log_audit_entry(
            event_type="generation_stream",
            msg="[API] Stream generation completed",
            status=AuditStatus.SUCCESS,
            details={
                "user_input": (
                    last_user_message["content"] if last_user_message else None
                ),
                "assistant_output": assistant_content,
                "assistant_reasoning": assistant_reasoning,
            },
            meta={
                "source": "model",
                "mode": "stream",
                "full_response": assistant_raw,
            },
        )

    finally:
        await safe_send({"type": "system", "event": "stream_end"})


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
# Playback
# ===========================================================
def play_message(msg_id: str):
    message = get_message_by_id(msg_id)
    if get_config_value("voice.enabled", False):
        set_speaking(True)
        threading.Thread(target=speak_line, args=(message["content"], False)).start()
    return message
