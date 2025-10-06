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
import json
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable

from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from modules.generative import NoProviderResolved, generation_manager
from modules.generative.types import GenerateRequest
from core.decision_layer import DecisionLayer
from services import database_service
from services.logger_service import log_audit_entry, AuditStatus
from modules.tts.state import VoiceStage, voice_state
from services.config_service import get_config_value
from services.database_service import get_message_by_id, add_message_to_history
from services.rag_service import retrieve_lore_fragments, format_lore_block
from utils.context_builder import build_memory_context
from utils.structure_utils import get_label_from_file
from core.prompt_loader import load_system_prompt
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
# History sanitization
# ===========================================================
def _sanitize_history(history: list, *, drop_media: bool) -> list:
    sanitized: list = []
    for message in history or []:
        base = {k: v for k, v in message.items() if k != "timestamp"}
        media = base.get("media")
        if media:
            if drop_media:
                base.pop("media", None)
            else:
                safe_media = []
                for item in media or []:
                    if isinstance(item, dict):
                        safe_media.append(
                            {k: v for k, v in item.items() if k != "data"}
                        )
                base["media"] = safe_media
        sanitized.append(base)
    return sanitized


# ===========================================================
# Build request
# ===========================================================
def build_chat_request(history, include_system=True):
    """
    System prompt is already embedded in history; we only strip timestamps.
    """
    return _sanitize_history(history, drop_media=True)


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
        details={"inputs": {"history": _sanitize_history(history, drop_media=False)}},
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
    request_payload = GenerateRequest(
        messages=full_history,
        options=options,
        metadata={"mode": "standard"},
    )

    try:
        generate_result = generation_manager.generate(request_payload)
    except NoProviderResolved as exc:
        log_audit_entry(
            event_type="generation_provider_failure",
            msg="[API] Не удалось подобрать провайдера генерации",
            status=AuditStatus.ERROR,
            details={"error": str(exc)},
        )
        raise RuntimeError("Generation provider not available") from exc

    assistant_raw = (generate_result.content or "").strip()
    raw_response = generate_result.raw
    assistant_content, assistant_reasoning = split_reasoning(assistant_raw)

    # === Save messages ===
    if last_user_message:
        database_service.add_message_to_history(
            character_name=char_name,
            role="user",
            content=last_user_message["content"],
            timestamp=last_user_message.get("timestamp"),
            media=last_user_message.get("media"),
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
        decision_layer_router.handle_response(assistant_content)

    # Logging
    log_audit_entry(
        event_type="generation_standard",
        msg="[API] Generate completed",
        status=AuditStatus.SUCCESS,
        details={
            "user_input": last_user_message["content"] if last_user_message else None,
            "assistant_output": assistant_content,
            "assistant_reasoning": assistant_reasoning,
            "provider": generate_result.provider,
        },
        meta={
            "source": "model",
            "mode": "standard",
            "provider": generate_result.provider,
            "full_response": raw_response,
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
        details={"inputs": {"history": _sanitize_history(history, drop_media=False)}},
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
                media=last_user_message.get("media"),
            )
            if last_user_message.get("id"):
                if not await safe_send(
                    {
                        "type": "ack_message",
                        "tempId": last_user_message.get("id"),
                        "realId": user_message_obj.id,
                        "media": getattr(user_message_obj, "media_payload", []),
                    }
                ):
                    return

        raw_chunks: list[str] = []
        streaming_in_reasoning = False
        voice_enabled = get_config_value("voice.enabled", False)
        streaming_tts = get_config_value("voice.streaming_tts", False)

        if voice_enabled and streaming_tts:
            log_audit_entry(
                "voice_streaming_unsupported",
                "[Voice] Streaming TTS not supported in current implementation",
                AuditStatus.WARNING,
            )
            streaming_tts = False

        speech_started = False
        provider_used_stream = None

        request_payload = GenerateRequest(
            messages=full_history,
            options=options,
            metadata={"mode": "stream"},
        )

        try:
            async for chunk in generation_manager.stream(request_payload):
                if provider_used_stream is None:
                    provider_used_stream = chunk.provider

                content = chunk.content or ""
                if isinstance(content, str) and content:
                    if not await safe_send(
                        {
                            "type": "message_chunk",
                            "role": "assistant",
                            "content": content,
                        }
                    ):
                        return
                    raw_chunks.append(content)

                    speech_chunk, _, streaming_in_reasoning = (
                        strip_reasoning_from_chunk(content, streaming_in_reasoning)
                    )

        except NoProviderResolved as exc:
            await safe_send(
                {"type": "error", "message": "Generation provider not available"}
            )
            log_audit_entry(
                event_type="generation_provider_stream_failure",
                msg="[API] Потоковый провайдер недоступен",
                status=AuditStatus.ERROR,
                details={"error": str(exc)},
            )
            return

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
            decision_layer_router.handle_response(assistant_content)

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
                "provider": provider_used_stream,
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
        decision_layer_router.handle_response(message.get("content", ""))
    return message


decision_layer_router = DecisionLayer()
