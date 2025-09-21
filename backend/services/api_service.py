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
from services.config_service import get_config_value
from services.database_service import get_message_by_id, add_message_to_history
from services.rag_service import retrieve_lore_fragments, format_lore_block
from services.ollama_service import api_stream
from utils.context_builder import build_memory_context
from utils.structure_utils import get_label_from_file
from utils.open_file_w_utf8 import open_utf8
from core.emotion_intent_analyzer import analyze_emotion, generate_instruction


THINK_PATTERN = re.compile(r"<think>(.*?)</think>", re.IGNORECASE | re.DOTALL)


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
        system_prompt = add_vision_context_to_system_prompt(
            base_system_prompt,
            last_user_message["content"] if last_user_message else "",
        )
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
        system_prompt = add_vision_context_to_system_prompt(
            base_system_prompt,
            last_user_message["content"] if last_user_message else "",
        )
        # Only append RAG, memory, and emotion blocks when using the fallback
        if last_user_message:
            rag_block = format_lore_block(
                retrieve_lore_fragments(last_user_message["content"])
            )
            memory_block = build_memory_context(last_user_message["content"], char_name)
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

    if voice_enabled:
        set_speaking(True)

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
                buffer.append(speech_chunk)
                buf_text = "".join(buffer)

                if len(buf_text) > 50 or buf_text.endswith((".", "!", "?")):
                    devices = []
                    if get_config_value("voice.use_windows_output", True):
                        devices.append(get_config_value("voice.windows_output_id", 0))
                    if get_config_value("voice.use_rvc", False):
                        devices.append(get_config_value("voice.output_id", 0))

                    tts_queue.put((buf_text, devices))
                    buffer = []

    if voice_enabled and streaming_tts and buffer:
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

    if voice_enabled and not streaming_tts and assistant_content:
        set_speaking(True)
        threading.Thread(target=speak_line, args=(assistant_content, False)).start()

    log_audit_entry(
        event_type="generation_stream",
        msg="[API] Stream generation completed",
        status=AuditStatus.SUCCESS,
        details={
            "user_input": last_user_message["content"] if last_user_message else None,
            "assistant_output": assistant_content,
            "assistant_reasoning": assistant_reasoning,
        },
        meta={
            "source": "model",
            "mode": "stream",
            "full_response": assistant_raw,
        },
    )

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


# ===========================================================
# Vision Context Integration (Appended at the end of the file)
# ===========================================================
def add_vision_context_to_system_prompt(
    base_system_prompt: str, last_user_message_content: str = ""
) -> str:
    """
    Добавляет визуальный контекст к системному промпту.
    Использует FastVLM для детального описания экрана или OCR/YOLO как фолбэк.
    """
    session_id = "unknown_session"  # In case get_session_id is unavailable
    try:
        from services.logger_service import get_session_id  # Import if available

        session_id = get_session_id()
    except ImportError:
        pass

    event_prefix = "vision_context"

    if not get_config_value("vision.enabled", False):
        # Log as INFO, as this is expected behavior
        log_audit_entry(
            event_type=f"{event_prefix}_disabled",
            msg="[Vision Context] Визуальный модуль отключен в конфигурации.",
            status=AuditStatus.INFO,
            meta={"session_id": session_id},
        )
        return base_system_prompt

    visual_module_instance = None
    try:
        from modules.vision.service import VisionService
        from core.visual_module import VisualModule

        log_audit_entry(
            event_type=f"{event_prefix}_init",
            msg="[Vision Context] Создаю экземпляр VisualModule...",
            status=AuditStatus.INFO,
            meta={"session_id": session_id},
        )
        visual_module_instance = VisualModule()

        # --- Determine whether this is a vision query ---
        # Extend the keyword list
        vision_keywords = [
            "видела",
            "заметила",
            "на экране",
            "ты видишь",
            "ты это видела",
            "что видишь",
            "что на экране",
            "опиши экран",
            "расскажи, что на экране",
        ]
        is_vision_query = any(
            kw in last_user_message_content.lower() for kw in vision_keywords
        )
        log_audit_entry(
            event_type=f"{event_prefix}_query_check",
            msg=f"[Vision Context] Сообщение пользователя: '{last_user_message_content}'",
            status=AuditStatus.INFO,
            details={
                "is_vision_query": is_vision_query,
                "keywords_matched": [
                    kw
                    for kw in vision_keywords
                    if kw in last_user_message_content.lower()
                ],
            },
            meta={"session_id": session_id},
        )

        # --- Gather baseline analysis (OCR/YOLO) ---
        log_audit_entry(
            event_type=f"{event_prefix}_analyzing",
            msg="[Vision Context] Запрашиваю анализ у VisionService...",
            status=AuditStatus.INFO,
            meta={"session_id": session_id},
        )
        vision_service = VisionService()
        visual_data = vision_service.analyze_recent_context(4.0)
        confidence = visual_data.get("confidence", "N/A") if visual_data else "N/A"
        log_audit_entry(
            event_type=f"{event_prefix}_analyzed",
            msg=f"[Vision Context] Получен анализ от VisionService.",
            status=AuditStatus.INFO,
            details={
                "confidence": confidence,
                "summary_preview": (
                    visual_data.get("summary", "")[:100] if visual_data else None
                ),
            },
            meta={"session_id": session_id},
        )

        # --- Try using FastVLM ---
        if is_vision_query:
            log_audit_entry(
                event_type=f"{event_prefix}_vlm_check",
                msg="[Vision Context] Это визуальный запрос. Проверяю готовность VisualModule...",
                status=AuditStatus.INFO,
                meta={"session_id": session_id},
            )

            is_vm_ready = (
                visual_module_instance.is_ready() if visual_module_instance else False
            )
            log_audit_entry(
                event_type=f"{event_prefix}_vlm_status",
                msg=f"[Vision Context] Статус VisualModule: {'Готов' if is_vm_ready else 'Не готов'}.",
                status=AuditStatus.INFO,
                meta={"session_id": session_id},
            )

            if is_vm_ready:
                log_audit_entry(
                    event_type=f"{event_prefix}_vlm_fetching_frame",
                    msg="[Vision Context] VisualModule готов. Получаю кадры...",
                    status=AuditStatus.INFO,
                    meta={"session_id": session_id},
                )
                frames = vision_service.buffer.get_latest_frames(1)
                if frames:
                    log_audit_entry(
                        event_type=f"{event_prefix}_vlm_processing_image",
                        msg="[Vision Context] Получен кадр. Преобразую в PIL Image и вызываю describe_image...",
                        status=AuditStatus.INFO,
                        meta={"session_id": session_id},
                    )
                    try:
                        _, last_frame = frames[-1]
                        from PIL import Image
                        import cv2

                        img_rgb = cv2.cvtColor(last_frame, cv2.COLOR_BGR2RGB)
                        # Optionally shrink the image to save memory
                        # pil_img = Image.fromarray(img_rgb)
                        # if pil_img.width > 1024 or pil_img.height > 1024:
                        #     pil_img.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

                        pil_img = Image.fromarray(img_rgb)

                        # Invoke FastVLM
                        vlm_result = visual_module_instance.describe_image(
                            pil_img,
                            "Describe the screen in detail in English.",
                        )

                        log_audit_entry(
                            event_type=f"{event_prefix}_vlm_success",
                            msg="[Vision Context] Получен результат от VisualModule.",
                            status=AuditStatus.SUCCESS,
                            details={
                                "model": vlm_result.get("model"),
                                "prompt": vlm_result.get("prompt"),
                                "summary_preview": vlm_result.get("summary", "")[:150],
                                "status": vlm_result.get("status"),
                            },
                            meta={"session_id": session_id},
                        )

                        visual_summary = vlm_result.get("summary", "")
                        if visual_summary:
                            final_prompt = (
                                f"{base_system_prompt}\n\n[CONTEXT:VISUAL]: {visual_summary}"
                                "\n\n[INSTRUCTION]\n"
                                "You currently see on the user's screen: "
                                f"{visual_summary}. Reference relevant visual details "
                                "in your reply when helpful."
                            )
                            log_audit_entry(
                                event_type=f"{event_prefix}_vlm_added",
                                msg="[Vision Context] Добавлен контекст от VisualModule.",
                                status=AuditStatus.SUCCESS,
                                details={"summary_length": len(visual_summary)},
                                meta={"session_id": session_id},
                            )
                            return final_prompt
                        else:
                            log_audit_entry(
                                event_type=f"{event_prefix}_vlm_empty_summary",
                                msg="[Vision Context] VisualModule вернул пустой summary.",
                                status=AuditStatus.WARNING,
                                meta={"session_id": session_id},
                            )
                    except Exception as img_proc_err:
                        log_audit_entry(
                            event_type=f"{event_prefix}_vlm_image_error",
                            msg=f"[Vision Context] Ошибка при обработке изображения или вызове describe_image: {img_proc_err}",
                            status=AuditStatus.ERROR,
                            meta={"session_id": session_id},
                        )
                else:
                    log_audit_entry(
                        event_type=f"{event_prefix}_no_frames",
                        msg="[Vision Context] Нет доступных кадров для анализа VisualModule.",
                        status=AuditStatus.WARNING,
                        meta={"session_id": session_id},
                    )
            else:
                log_audit_entry(
                    event_type=f"{event_prefix}_vlm_not_ready",
                    msg="[Vision Context] VisualModule не готов для использования.",
                    status=AuditStatus.WARNING,
                    meta={"session_id": session_id},
                )
        else:
            log_audit_entry(
                event_type=f"{event_prefix}_not_vision_query",
                msg="[Vision Context] Запрос не распознан как визуальный.",
                status=AuditStatus.INFO,
                meta={"session_id": session_id},
            )

        # --- Fallback to OCR/YOLO ---
        if visual_data and visual_data.get("confidence", 0) > 0.5:
            ocr_yolo_summary = visual_data.get("summary", "")
            final_prompt = (
                f"{base_system_prompt}\n\n[CONTEXT:VISUAL]: {ocr_yolo_summary}"
                "\n\n[INSTRUCTION]\n"
                "You currently see on the user's screen: "
                f"{ocr_yolo_summary}. Reference relevant visual details in "
                "your reply when helpful."
            )
            log_audit_entry(
                event_type=f"{event_prefix}_ocr_yolo_added",
                msg="[Vision Context] Добавлен контекст от OCR/YOLO.",
                status=AuditStatus.SUCCESS,
                details={
                    "summary_preview": ocr_yolo_summary[:100],
                    "confidence": visual_data.get("confidence"),
                },
                meta={"session_id": session_id},
            )
            return final_prompt
        else:
            log_audit_entry(
                event_type=f"{event_prefix}_low_confidence",
                msg="[Vision Context] Уверенность OCR/YOLO низкая или данные отсутствуют.",
                status=AuditStatus.INFO,
                details={"confidence": confidence},
                meta={"session_id": session_id},
            )

    except Exception as e:
        log_audit_entry(
            event_type=f"{event_prefix}_error",
            msg=f"[Vision Context] Ошибка добавления контекста: {e}",
            status=AuditStatus.ERROR,
            details={"error": str(e)},
            meta={"session_id": session_id},
        )
        # On error, return the original prompt to avoid breaking the main flow
    finally:
        # --- Force resource cleanup ---
        if visual_module_instance is not None:
            # Remove the cached instance reference
            del visual_module_instance
            # Force garbage collection
            gc.collect()
            # Clear CUDA cache when available
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            log_audit_entry(
                event_type=f"{event_prefix}_cleanup",
                msg="[Vision Context] Ресурсы VisualModule освобождены.",
                status=AuditStatus.INFO,
                meta={"session_id": session_id},
            )

    log_audit_entry(
        event_type=f"{event_prefix}_fallback",
        msg="[Vision Context] Возвращаю оригинальный промпт без визуального контекста.",
        status=AuditStatus.INFO,
        meta={"session_id": session_id},
    )
    return base_system_prompt
