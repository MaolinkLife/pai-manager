from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from core.interaction import resolve_interaction_policy
from modules.system import auth as auth_service
from modules.telegram.runtime import (
    autostart_telegram_bridge,
    get_telegram_bridge_status,
    list_telegram_chats,
    ping_telegram_bridge,
    request_telegram_code,
    run_public_reflection_probe,
    send_telegram_test_image,
    stop_telegram_bridge,
    submit_telegram_code,
    submit_telegram_password,
)

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])


def _extract_user_uuid(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if not auth_header:
        return None
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    if not token:
        return None
    try:
        user = auth_service.get_user_from_access_token(token)
    except Exception:
        return None
    return user.uuid if user else None


def _require_owner(request: Request) -> str:
    actor_user_uuid = _extract_user_uuid(request)
    if not actor_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    interaction_policy = resolve_interaction_policy(actor_user_uuid)
    if not interaction_policy.can_affect_global_memory:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Telegram control is not available for current role",
        )
    return actor_user_uuid


@router.get("/status")
def telegram_status(request: Request):
    _require_owner(request)
    return {"status": "ok", "telegram": get_telegram_bridge_status()}


@router.post("/start")
async def telegram_start(request: Request):
    _require_owner(request)
    # payload is currently reserved for future runtime overrides.
    try:
        _ = await request.json()
    except Exception:
        pass
    started = autostart_telegram_bridge()
    return {
        "status": "ok",
        "started": bool(started),
        "telegram": get_telegram_bridge_status(),
    }


@router.post("/stop")
def telegram_stop(request: Request):
    _require_owner(request)
    was_running = stop_telegram_bridge()
    return {
        "status": "ok",
        "was_running": bool(was_running),
        "telegram": get_telegram_bridge_status(),
    }


@router.post("/ping")
def telegram_ping(request: Request):
    _require_owner(request)
    result = ping_telegram_bridge()
    return {"status": "ok" if result.get("ok") else "error", "ping": result}


@router.get("/chats")
def telegram_chats(
    request: Request,
    limit: int = 200,
    include_blocked: bool = True,
):
    _require_owner(request)
    result = list_telegram_chats(limit=limit, include_blocked=include_blocked)
    return {"status": "ok" if result.get("ok") else "error", "chats": result.get("chats", []), "error": result.get("error")}


@router.post("/auth/request_code")
async def telegram_auth_request_code(request: Request):
    _require_owner(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    phone_number = None
    if isinstance(payload, dict):
        phone_number = (payload.get("phone_number") or payload.get("phone") or "").strip() or None
    result = request_telegram_code(phone_number=phone_number)
    return {"status": "ok" if result.get("ok") else "error", "auth": result}


@router.post("/auth/submit_code")
async def telegram_auth_submit_code(request: Request):
    _require_owner(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    code = ""
    if isinstance(payload, dict):
        code = str(payload.get("code") or "").strip()
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="code is required",
        )
    result = submit_telegram_code(code=code)
    return {"status": "ok" if result.get("ok") else "error", "auth": result}


@router.post("/auth/submit_password")
async def telegram_auth_submit_password(request: Request):
    _require_owner(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    password = ""
    if isinstance(payload, dict):
        password = str(payload.get("password") or "").strip()
    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="password is required",
        )
    result = submit_telegram_password(password=password)
    return {"status": "ok" if result.get("ok") else "error", "auth": result}


@router.post("/test/public_reflection")
async def telegram_test_public_reflection(request: Request):
    _require_owner(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    source_chat_id = None
    if isinstance(payload, dict):
        raw = payload.get("source_chat_id")
        try:
            source_chat_id = int(raw) if raw is not None else None
        except Exception:
            source_chat_id = None
    result = run_public_reflection_probe(source_chat_id=source_chat_id)
    return {"status": "ok" if result.get("ok") else "error", "probe": result}


@router.post("/test/send_image")
async def telegram_test_send_image(request: Request):
    _require_owner(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    prompt = None
    target_chat_id = None
    caption = None
    if isinstance(payload, dict):
        prompt_raw = payload.get("prompt")
        if prompt_raw is not None:
            prompt = str(prompt_raw).strip() or None
        caption_raw = payload.get("caption")
        if caption_raw is not None:
            caption = str(caption_raw).strip() or None
        raw_chat_id = payload.get("target_chat_id")
        try:
            target_chat_id = int(raw_chat_id) if raw_chat_id is not None else None
        except Exception:
            target_chat_id = None
    result = send_telegram_test_image(
        prompt=prompt,
        target_chat_id=target_chat_id,
        caption=caption,
    )
    return {"status": "ok" if result.get("ok") else "error", "image_test": result}
