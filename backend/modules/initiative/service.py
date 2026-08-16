"""Chat initiative — PAI writes to main_chat first, optionally with a selfie.

Triggered by the initiative loop when the idle/emotion pattern fires
(«беспокойство» after 30 min of silence, etc.). The message is composed by
the generation LLM with the persona prompt attached; if composing fails the
initiative is skipped entirely — a canned line would break the voice.

The selfie rides the same media pipeline as the chat illustrate action
(visual intent → appearance anchor + time/emotion cues) and attaches to the
just-persisted message via message_media_update, so the bubble updates live.
Image generation is scheduled onto the main loop fire-and-forget: the loop
thread never blocks on GPU work and a failed selfie never cancels the text.
"""

from __future__ import annotations

import base64
import json
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


def _settings() -> Dict[str, Any]:
    cfg = config_service.get_config_value("initiative", {}) or {}
    chat = cfg.get("chat") if isinstance(cfg.get("chat"), dict) else {}
    selfie = cfg.get("selfie") if isinstance(cfg.get("selfie"), dict) else {}
    return {
        "enabled": bool(chat.get("enabled", True)),
        "selfie_enabled": bool(selfie.get("enabled", True)),
        "selfie_chance": max(0.0, min(1.0, float(selfie.get("chance", 0.4) or 0.0))),
    }


def run_chat_initiative(emotion: str) -> Optional[str]:
    """Compose, persist and broadcast an initiative message; maybe a selfie.

    Called from the initiative loop thread. Returns the message id or None
    when disabled/failed (the loop treats None as «не сложилось, не страшно»).
    """
    settings = _settings()
    if not settings["enabled"]:
        return None

    from modules.database import service as database_service
    from modules.system.service import get_active_character_name

    character_name = get_active_character_name(default="default_waifu")
    content = _compose_initiative_text(emotion, character_name)
    if not content:
        log_audit_entry(
            "initiative_compose_skipped",
            "[Initiative] Composer returned no text — initiative skipped.",
            AuditStatus.INFO,
            details={"emotion": emotion},
        )
        return None

    now = datetime.now(timezone.utc)
    row = database_service.add_message_to_history(
        character_name=character_name,
        role="assistant",
        content=content,
        timestamp=now,
        tags=["initiative"],
        runtime_meta={
            "source": "initiative",
            "event": "chat_initiative",
            "emotion": emotion,
        },
    )
    message_id = getattr(row, "id", None)
    _broadcast_ws({
        "type": "message",
        "id": message_id,
        "role": "assistant",
        "content": content,
        "timestamp": now.isoformat(),
        "source": "initiative",
    })
    log_audit_entry(
        "initiative_message_sent",
        "[Initiative] Initiative message delivered to main_chat.",
        AuditStatus.SUCCESS,
        details={"message_id": message_id, "emotion": emotion},
    )

    if (
        message_id
        and settings["selfie_enabled"]
        and random.random() < settings["selfie_chance"]
    ):
        _schedule_selfie(str(message_id), content)

    return message_id


def _compose_initiative_text(emotion: str, character_name: str) -> str:
    try:
        from constants.prompts import INITIATIVE_CHAT_PROMPT
        from core.prompt_loader import load_system_prompt
        from modules.database import service as database_service
        from modules.generative.manager import generation_manager
        from modules.generative.types import GenerateRequest
        from modules.system.user import resolve_user_language

        last_user_message = ""
        try:
            recent = database_service.get_last_messages(character_name, limit=10) or []
            for item in reversed(recent):
                if str(item.get("role") or "") == "user":
                    last_user_message = str(item.get("content") or "")[:400]
                    break
        except Exception:
            pass

        language = resolve_user_language(fallback="en-US")
        prompt = INITIATIVE_CHAT_PROMPT.format(
            emotion=emotion,
            last_user_message=last_user_message or "—",
            now_local=datetime.now().strftime("%Y-%m-%d %H:%M"),
            language=language,
        )
        messages = []
        try:
            persona = str(load_system_prompt() or "").strip()
            if persona and not persona.startswith("[System Error]"):
                messages.append({"role": "system", "content": persona})
        except Exception:
            pass
        messages.append({"role": "system", "content": prompt})
        result = generation_manager.generate(
            GenerateRequest(
                messages=messages,
                options={"temperature": 0.85, "num_predict": 300, "__think": False},
                metadata={"mode": "chat_initiative"},
            )
        )
        return str(getattr(result, "content", "") or "").strip()
    except Exception as exc:
        log_audit_entry(
            "initiative_compose_failed",
            "[Initiative] Initiative text composing failed.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return ""


def _broadcast_ws(payload: Dict[str, Any]) -> bool:
    """Schedule a WS broadcast onto the uvicorn loop from the worker thread."""
    try:
        import asyncio

        from core.event_loop_registry import get_main_loop
        from core.websocket_manager import manager

        loop = get_main_loop()
        if loop is None:
            return False
        future = asyncio.run_coroutine_threadsafe(
            manager.send_message(json.dumps(payload, ensure_ascii=False)), loop
        )
        future.result(timeout=5)
        return True
    except Exception:
        return False


def _schedule_selfie(message_id: str, content: str) -> None:
    """Fire-and-forget: GPU work must not block the initiative loop thread."""
    try:
        import asyncio

        from core.event_loop_registry import get_main_loop

        loop = get_main_loop()
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(_attach_selfie(message_id, content), loop)
    except Exception:
        pass


async def _attach_selfie(message_id: str, content: str) -> None:
    """Generate a selfie for the initiative message and attach it.

    Same machinery as the chat illustrate action: media pipeline with visual
    intent (appearance anchor + time/emotion/outfit cues resolve the selfie
    look), save_media_for_message, message_media_update over WS.
    """
    try:
        from core.websocket_manager import manager
        from modules.memory.history import get_message_by_id
        from modules.storage.service import save_media_for_message
        from modules.synthesis.media_pipeline import (
            MediaPipelineRequest,
            media_generation_pipeline,
        )
        from modules.system.config import get_config_value
        from modules.system.service import get_active_character_name

        image_cfg = get_config_value("telegram.image", {}) or {}
        result = await media_generation_pipeline.run_image(
            MediaPipelineRequest(
                mode="chat_auto",
                prompt=content[:2000],
                scenario_key="main_chat",
                negative_prompt=str(image_cfg.get("negative_prompt") or ""),
                image_provider="auto",
                image_model=str(image_cfg.get("default_model") or "").strip() or None,
                width=max(64, int(image_cfg.get("width", 1024) or 1024)),
                height=max(64, int(image_cfg.get("height", 1024) or 1024)),
                num_inference_steps=max(1, int(image_cfg.get("num_inference_steps", 9) or 9)),
                guidance_scale=float(image_cfg.get("guidance_scale", 0.0) or 0.0),
                use_prompt_builder=False,
                review_generated_image=False,
                use_visual_intent=True,
                source="main_chat_initiative",
                character_name=get_active_character_name(default="PAI"),
                metadata={"allow_scenario_controls": True, "purpose_hint": "check_in"},
            )
        )
        if not getattr(result, "image_bytes", b""):
            raise RuntimeError("Image generation returned no data")

        media_item = {
            "id": str(uuid.uuid4()),
            "name": f"initiative_selfie_{int(time.time())}.png",
            "mimeType": str(getattr(result, "mime_type", "") or "image/png"),
            "category": "image",
            "size": len(result.image_bytes),
            "description": (getattr(result, "vision_description", "") or result.image_prompt or content)[:900],
            "data": result.image_base64 or base64.b64encode(result.image_bytes).decode("ascii"),
        }
        save_media_for_message(message_id, [media_item])

        updated = get_message_by_id(message_id)
        media_payload = (updated or {}).get("media") or []
        try:
            await manager.send_message(json.dumps({
                "type": "message_media_update",
                "id": message_id,
                "media": media_payload,
            }, ensure_ascii=False))
        except Exception:
            pass

        log_audit_entry(
            "initiative_selfie_attached",
            "[Initiative] Selfie attached to initiative message.",
            AuditStatus.SUCCESS,
            details={
                "message_id": message_id,
                "provider": getattr(result, "provider", None),
                "bytes": media_item["size"],
            },
        )
    except Exception as exc:
        log_audit_entry(
            "initiative_selfie_failed",
            "[Initiative] Selfie generation failed (text already delivered).",
            AuditStatus.WARNING,
            details={"message_id": message_id, "error": str(exc)},
        )
