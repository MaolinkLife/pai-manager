# ===========================================================
# Module: ollama_routes.py
# Purpose: Endpoints for interacting with the Ollama model and getting history
# Used in: WebUI or other clients sending requests to LLM
# Features:
# - Delegates message preparation to api_service and transport to ollama client utils
# - Has endpoints for getting the list of models and history
# ========================================================

from fastapi import APIRouter, Query, Request, HTTPException, status
from fastapi.responses import JSONResponse

from modules.generative import conversation
from core.decision_layer import decision_layer
from modules.ollama import client as ollama_client

# from services.history_service import get_history
from modules.database import service as database_service
from modules.system.logger import log_audit_entry, AuditStatus
from core.interaction import (
    resolve_actor_uuid_from_auth_header,
    resolve_interaction_policy,
)
from modules.system.service import get_active_character_name

router = APIRouter(prefix="/api/ollama", tags=["Ollama"])


# Sending messages to Ollama (chat request)
@router.post("/chat")
async def chat(payload: dict, request: Request):
    history = payload.get("history", [])
    last_user = next(
        (msg for msg in reversed(history) if msg.get("role") == "user"), None
    )
    if not last_user:
        return {"status": "error", "message": "No user message provided"}

    user_input = dict(last_user)
    user_input.setdefault("history", history[:-1])
    actor_user_uuid = resolve_actor_uuid_from_auth_header(
        request.headers.get("authorization")
    )
    if actor_user_uuid:
        user_input["actor_user_uuid"] = actor_user_uuid
    interaction_policy = resolve_interaction_policy(actor_user_uuid)

    decision_context = await decision_layer.process_message(user_input, None)
    decision_context.pop("raw_media", None)
    response = await conversation.generate_standard(
        decision_context,
        history,
        user_input,
        store=interaction_policy.can_affect_global_memory,
    )
    return {"response": response}


# Returns a list of available Ollama models.
@router.get("/models")
async def get_available_models():
    return ollama_client.list_models()


@router.get("/runtime/models")
async def get_runtime_models():
    return ollama_client.list_runtime_models()


@router.post("/runtime/unload")
async def unload_runtime_model(payload: dict):
    model = str(payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")
    result = ollama_client.release_model(model)
    if result.get("status") != "ok":
        return JSONResponse(status_code=500, content=result)
    return result


@router.post("/capabilities/check")
async def check_model_capabilities(payload: dict):
    model = str(payload.get("model") or "").strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")

    checks = payload.get("checks")
    if not isinstance(checks, dict):
        checks = {"tool": True, "vision": True, "thinking": True}

    result = {
        "status": "ok",
        "model": model,
        "capabilities": {
            "tool": False,
            "vision": False,
            "thinking": False,
        },
        "details": {},
    }

    if checks.get("tool"):
        tool_result = await _probe_tool_support(model)
        result["capabilities"]["tool"] = bool(tool_result.get("supported"))
        result["details"]["tool"] = tool_result

    if checks.get("vision"):
        vision_result = await _probe_vision_support(model)
        result["capabilities"]["vision"] = bool(vision_result.get("supported"))
        result["details"]["vision"] = vision_result

    if checks.get("thinking"):
        thinking_result = await _probe_thinking_support(model)
        result["capabilities"]["thinking"] = bool(thinking_result.get("supported"))
        result["details"]["thinking"] = thinking_result

    return result


async def _probe_tool_support(model: str) -> dict:
    import asyncio

    tool = {
        "type": "function",
        "function": {
            "name": "mark_capability",
            "description": "Mark that tool calling is supported.",
            "parameters": {
                "type": "object",
                "properties": {"supported": {"type": "boolean"}},
                "required": ["supported"],
            },
        },
    }
    try:
        raw = await asyncio.to_thread(
            ollama_client.chat_with_tools,
            [
                {
                    "role": "system",
                    "content": "Call the mark_capability tool with supported=true.",
                },
                {"role": "user", "content": "Run the capability check."},
            ],
            {"temperature": 0, "num_predict": 64},
            model,
            tools=[tool],
            tool_choice={"type": "function", "function": {"name": "mark_capability"}},
        )
        calls = ((raw or {}).get("message") or {}).get("tool_calls") or []
        supported = any(
            ((call or {}).get("function") or {}).get("name") == "mark_capability"
            for call in calls
        )
        return {"supported": supported}
    except Exception as exc:
        return {"supported": False, "error": str(exc)}


async def _probe_vision_support(model: str) -> dict:
    import asyncio

    metadata_support = ollama_client.model_supports_vision(model)
    if not metadata_support.get("supported"):
        return {
            "supported": False,
            "metadata": metadata_support,
            "error": metadata_support.get("reason") or "model metadata does not declare vision support",
        }

    # 1x1 red PNG.
    image_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR4nGP4z8DwHwAF"
        "gAL+QnZ9TAAAAABJRU5ErkJggg=="
    )
    try:
        text = await asyncio.to_thread(
            ollama_client.chat_image,
            [
                {
                    "role": "user",
                    "content": "Describe this image in one short phrase.",
                    "images": [image_b64],
                }
            ],
            model,
            options={"temperature": 0, "num_predict": 64},
        )
        normalized = (text or "").strip().lower()
        supported = bool(normalized) and not normalized.startswith("[error]")
        return {"supported": supported, "sample": text[:200], "metadata": metadata_support}
    except Exception as exc:
        return {"supported": False, "error": str(exc), "metadata": metadata_support}


async def _probe_thinking_support(model: str) -> dict:
    import asyncio

    try:
        raw = await asyncio.to_thread(
            ollama_client.chat_with_tools,
            [
                {
                    "role": "user",
                    "content": "Answer with the single word OK. Use internal reasoning if your model supports it.",
                }
            ],
            {"temperature": 0, "num_predict": 96},
            model,
        )
        message = (raw or {}).get("message") or {}
        content = str(message.get("content") or "")
        thinking = str(message.get("thinking") or raw.get("thinking") or "")
        model_hint = any(
            marker in model.lower()
            for marker in ("r1", "qwq", "reason", "thinking")
        )
        supported = bool(thinking.strip()) or "<think>" in content.lower() or model_hint
        return {"supported": supported, "has_thinking_field": bool(thinking.strip())}
    except Exception as exc:
        return {"supported": False, "error": str(exc)}


@router.get("/history")
async def fetch_history(request: Request, limit: int = 32):
    actor_user_uuid = resolve_actor_uuid_from_auth_header(
        request.headers.get("authorization")
    )
    interaction_policy = resolve_interaction_policy(actor_user_uuid)
    if not interaction_policy.can_affect_global_memory:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="History access is not available for current role",
        )
    try:
        char_name = get_active_character_name(
            user_uuid=actor_user_uuid,
            default="default_waifu",
        )
        history = database_service.get_history(char_name, limit)
        return JSONResponse(content={"status": "ok", "history": history})
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@router.delete("/history/message")
async def delete_message_api(
    request: Request, message_id: str, chain: bool = False
):
    actor_user_uuid = resolve_actor_uuid_from_auth_header(
        request.headers.get("authorization")
    )
    interaction_policy = resolve_interaction_policy(actor_user_uuid)
    if not interaction_policy.can_affect_global_memory:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delete is not available for current role",
        )
    try:
        if chain:
            return database_service.delete_message_chain(message_id)
        else:
            return database_service.delete_message(message_id)
    except Exception as e:
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@router.post("/history/reroll")
async def reroll_assistant_message(payload: dict, request: Request):
    actor_user_uuid = resolve_actor_uuid_from_auth_header(
        request.headers.get("authorization")
    )
    interaction_policy = resolve_interaction_policy(actor_user_uuid)
    if not interaction_policy.can_affect_global_memory:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reroll is not available for current role",
        )
    try:
        message_id = payload.get("message_id")
        if not message_id:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "message_id is required"},
            )

        new_reply = database_service.reroll_message(message_id)
        return JSONResponse(content={"status": "ok", "new_message": new_reply})

    except Exception as e:
        log_audit_entry(
            event_type="reroll_request_error",
            msg="[Ollama Router]: Error while executing rerolll",
            status=AuditStatus.ERROR,
            details={"input": payload, "error": str(e)},
        )
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )
