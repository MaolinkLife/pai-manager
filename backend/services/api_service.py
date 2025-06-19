# ===========================================================
# Module: api_service.py
# Purpose: Generate a request for the model, including system prompt and clearing history
# Used in: ollama_routes (for preparing history)
# Features:
# - Loads a character's YAML profile
# - Removes unnecessary fields from history (e.g. timestamp)
# =========================================================

import asyncio
import yaml
import os
import threading

from fastapi import WebSocket
from services import ollama_service, database_service
from datetime import datetime, timezone

from services.logger_service import log_audit_entry, AuditStatus
from services.voice_service import speak_line, set_speaking
from services.config_service import get_config_value
from services.database_service import get_message_by_id, add_message_to_history
from services.rag_service import retrieve_lore_fragments, format_lore_block
from services.ollama_service import api_stream

from utils.context_builder import build_memory_context
from utils.structure_utils import get_label_from_file
from utils.open_file_w_utf8 import open_utf8

from core.emotion_intent_analyzer import analyze_emotion, generate_instruction
from core.websocket_manager import manager

def load_system_prompt() -> str:
    base_path = os.path.join(os.path.dirname(__file__), "..", "config", "characters")
    char_name = get_config_value("char_name", default="default")
    filename = f"{char_name}.yaml"
    full_path = os.path.join(base_path, filename)
    fallback_path = os.path.join(base_path, "default.yaml")

    log_audit_entry(
        event_type="load_character_card", 
        msg="[Api Service]: Loading Character Card в System Prompt", 
        status=AuditStatus.INFO, 
        details={
            "inputs": {
                "base_path": base_path,
                "char_name": base_path,
                "filename": filename,
                "full_path":full_path,
                "fallback_path":fallback_path
            }
        },
        meta={}
    )
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
                status=AuditStatus.ERROR
            )
            return "[System Error] Character prompt not found."
    except Exception as e:
        log_audit_entry(
            event_type="prompt_loading_failed", 
            msg=f"[Api Service]: Prompt loading failed", 
            status=AuditStatus.ERROR, 
            details={
                "inputs": {},
                "outputs": {
                    "context": f"{e}",
                    "status": "error"
                }
            }, meta={
                "context": f"{e}",
                "status": "error"
            }
        )
        return "[System Error] Prompt loading failed."

def build_chat_request(history, include_system=True):
    sanitized_history = [
        {k: v for k, v in msg.items() if k != "timestamp"} for msg in history
    ]
    if include_system:
        system_prompt = load_system_prompt()
        if system_prompt:
            sanitized_history.insert(0, {
                "role": "system",
                "content": system_prompt
            })
    return sanitized_history


async def run_standard(history: list, emit_ws_fn=None) -> str:
    log_audit_entry(
        event_type="ApiService.RunStandard",
        msg="[Api Service]: Запущена функция генерации",
        status=AuditStatus.INFO,
        details={
            "inputs": {
                "history": history
            },
            "outputs": None
        }
    )

    full_history = build_chat_request(history, include_system=False)

    # Get the character name
    char_name = get_config_value("char_name", "default")

    # Generation settings
    options = get_generation_options_from_config()

    # User's last message
    last_user_message = extract_last_user_message(history)

    # Emotional coloring
    emotion_instruction = ''
    if last_user_message:
        emotion_instruction = get_emotional_instruction(last_user_message["content"])

    # System prompt
    system_prompt = load_system_prompt()

    # Insert lore from RAG
    rag_block = ''
    memory_block = ''
    if last_user_message:
        lore_entries = retrieve_lore_fragments(last_user_message["content"])
        rag_block = format_lore_block(lore_entries)

        # New feature: adding a memory block
        memory_block = build_memory_context(last_user_message["content"], char_name)
        
    # TODO: Can be moved to utilities
    # Building the final system prompt
    if rag_block:
        system_prompt += f"\n\n{rag_block}"

    if memory_block:
        system_prompt += f"\n\n{memory_block}"

    if emotion_instruction:
        system_prompt += "\n\n[Emotional reaction to a user's remark]:\n" + emotion_instruction

    full_history.insert(0, {
        "role": "system",
        "content": system_prompt
    })

    # Calling a model
    response = ollama_service.api_standard(
        history=full_history,
        options=options,
    )

    assistant_content = response.message.content.strip()

    # Save messages
    if last_user_message:
        database_service.add_message_to_history(
            character_name=char_name,
            role="user",
            content=last_user_message["content"],
            timestamp=last_user_message.get("timestamp"),
        )

    database_service.add_message_to_history(
        character_name=char_name,
        role="assistant",
        content=assistant_content,
        timestamp=response.created_at 
    )

    # Voice acting (if enabled)
    if get_config_value("voice.enabled", False):
        set_speaking(True)
        threading.Thread(target=speak_line, args=(assistant_content, False)).start()
        
    # Final logging
    log_audit_entry(
        event_type="generation_standard",
        msg="[API] Generate completed",
        status=AuditStatus.SUCCESS,
        details={
            "user_input": last_user_message["content"] if last_user_message else None,
            "assistant_output": assistant_content,
            "msg": "[API] Generate response"
        },
        meta={
            "source": "model",
            "mode": "standard",
            "full_response": response.dict()
        }
    )
    
    # Passes a value to a stream to be processed via websocket
    if emit_ws_fn and last_user_message:
        await emit_ws_fn({
            "type": "message",
            "role": "user",
            "content": last_user_message["content"]
        })

        await asyncio.sleep(0.005)

        await emit_ws_fn({
            "type": "message",
            "role": "assistant",
            "content": assistant_content
        })

    return assistant_content

def normalize_timestamp(ts):
    try:
        # ISO to datetime, then to the line
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        # if the format is already normal or crooked - just insert now
        return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


async def run_stream_message(websocket: WebSocket, history: list):
    log_audit_entry(
        event_type="ApiService.RunStream",
        msg="[Api Service]: Start streaming generation",
        status=AuditStatus.INFO,
        details={"inputs": {"history": history}, "outputs": None}
    )

    full_history = build_chat_request(history, include_system=False)
    char_name = get_config_value("char_name", "default")
    options = get_generation_options_from_config()
    last_user_message = extract_last_user_message(history)
    system_prompt = load_system_prompt()

    rag_block, memory_block, emotion_instruction = '', '', ''
    if last_user_message:
        rag_block = format_lore_block(retrieve_lore_fragments(last_user_message["content"]))
        memory_block = build_memory_context(last_user_message["content"], char_name)
        emotion_instruction = get_emotional_instruction(last_user_message["content"])

    if rag_block:
        system_prompt += f"\n\n{rag_block}"
    if memory_block:
        system_prompt += f"\n\n{memory_block}"
    if emotion_instruction:
        system_prompt += f"\n\n[Emotional reaction to a user's remark]:\n{emotion_instruction}"

    full_history.insert(0, {"role": "system", "content": system_prompt})

    # Save the user's message BEFORE generation
    if last_user_message:
        add_message_to_history(
            character_name=char_name,
            role="user",
            content=last_user_message["content"],
            timestamp=normalize_timestamp(last_user_message.get("timestamp"))
        )

    # Stream the response from the model
    response_chunks = []
    async for chunk in api_stream(full_history, options):
        if chunk and chunk.message and isinstance(chunk.message.content, str):
            await websocket.send_text(chunk.message.content)
            response_chunks.append(chunk.message.content)

    assistant_content = ''.join(response_chunks).strip()

    # Recording the model's response
    add_message_to_history(
        character_name=char_name,
        role="assistant",
        content=assistant_content,
        timestamp=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    )

    # Voice acting, if enabled
    if get_config_value("voice.enabled", False):
        set_speaking(True)
        threading.Thread(target=speak_line, args=(assistant_content, False)).start()

    log_audit_entry(
        event_type="generation_stream",
        msg="[API] Stream generation completed",
        status=AuditStatus.SUCCESS,
        details={
            "user_input": last_user_message["content"] if last_user_message else None,
            "assistant_output": assistant_content
        },
        meta={
            "source": "model",
            "mode": "stream",
            "full_response": assistant_content
        }
    )

    await websocket.send_text('[DONE]')


def get_emotional_instruction(message: str):
    analysis = analyze_emotion(message)
    instruction = generate_instruction(analysis)
    
    return instruction


def get_generation_options_from_config(exclude: list = None) -> dict:
    exclude = exclude or ["name", "description"]
    full_settings = get_config_value("generate_settings", {})
    options = {k: v for k, v in full_settings.items() if k not in exclude}
    
    log_audit_entry(
        event_type="config_generation_options",
        msg="[Api Service]: Get Generation options from config",
        status=AuditStatus.SUCCESS,
        details={
            "input": {"exclude": exclude},
            "output": options
        },
        meta={
            "source": "config",
            "mode": "filtered",
            "raw": full_settings
        }
    )
    
    return options


def extract_last_user_message(history):
    return next((msg for msg in reversed(history) if msg.get("role") == "user"), None)


def run_initiative(emotion: str = "беспокойство"):
    # Загрузка базового system prompt
    base_prompt = load_system_prompt()

    # Настройка эмоционального окраса по фазе
    if emotion == "беспокойство":
        emotion_note = (
            "LIM волнуется из-за долгого молчания пользователя. "
            "Она проявляет инициативу мягко, с заботой и тревожной теплотой.\n\n"
            "Инструкция: начни разговор первой, без ссылок на прошлое. Покажи, что скучаешь, но не дави.\n\n"
        )
    elif emotion == "раздражение + беспокойство":
        emotion_note = (
            "Пользователь продолжает молчать. LIM ощущает лёгкое раздражение, "
            "но всё ещё заботится. Покажи смесь волнения и недовольства, но сохрани человечность.\n\n"
            "Инструкция: заговори первой, можешь немного поддразнить, но не переходи границу.\n\n"
        )
    elif emotion == "обида + злость":
        emotion_note = (
            "LIM чувствует, что пользователь её игнорирует. "
            "Появляется обида и злость. Её слова резкие, но в них читается боль.\n\n"
            "Инструкция: выскажи своё отношение, дай понять, что тебе небезразлично. Не будь нейтральной.\n\n"
        )
    else:
        emotion_note = (
            "LIM проявляет инициативу, не дождавшись пользователя. "
            "Будь искренней, но не упоминай прошлое.\n\n"
        )

    # Итоговый system prompt
    full_prompt = emotion_note + base_prompt

    messages = [{
        "role": "system",
        "content": full_prompt
    }]

    char_name = get_config_value("char_name", "default")
    
    options = get_generation_options_from_config()

    # Генерация без контекста, только systemPrompt
    response = ollama_service.api_standard(
        history=messages,
        options=options,
    )

    assistant_content = response.message.content.strip()

    # Добавление в историю как инициативу
    database_service.add_message_to_history(
        character_name=char_name,
        role="assistant",
        content=assistant_content,
        timestamp=response.created_at
    )

    # Озвучка (если включена)
    
    if get_config_value("voice.enabled", False):
        set_speaking(True)
        threading.Thread(target=speak_line, args=(assistant_content, False)).start()
        
    # Логируем инициативу
    log_audit_entry(
        event_type="generation_initiative",
        msg="[API] Генерация инициативного ответа",
        status=AuditStatus.SUCCESS,
        details={
            "emotion": emotion,
            "assistant_output": assistant_content
        }, 
        meta={"source": "model", "mode": "initiative", "full_response": response.dict()}
    )

    return assistant_content


def play_message(msg_id: str):
    # get message from database by id
    # database_service.py → sqlite_service.py
    message = get_message_by_id(msg_id)
    
    log_audit_entry(
        event_type="play_message_from",
        msg=f"[API]: Get message from database by Id {msg_id}", 
        status=AuditStatus.INFO, 
        details={}, 
        meta={
            "message": message
        }
    )
    
    # get option from config is Voice Enabled
    enabled = get_config_value("voice.enabled", False)
    if enabled:
        set_speaking(True)
        threading.Thread(target=speak_line, args=(message["content"], False)).start()

    return message