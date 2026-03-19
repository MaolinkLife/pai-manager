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
from services import database_service
from services.logger_service import log_audit_entry, AuditStatus
from services.interaction_policy import (
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
