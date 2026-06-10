# ===========================================================
# Module: config_routes.py
# Purpose: API endpoints for working with PAI configuration
# Used in: WebUI and any external components that need to read/change config
# Features:
# - Supports full replacement and partial update
# - Returns the entire config via GET request
# ========================================================

import ast

from fastapi import APIRouter, HTTPException, Request, status
from modules.system.character import (
    create_character_record,
    delete_character_record,
    get_active_character_for_user,
    get_character_prompt,
    import_character_yaml_text,
    list_characters,
    resolve_active_character_name_for_user,
    save_character_prompt,
    set_active_character_for_user,
)
from modules.system import auth as auth_service
from modules.system import service as system_service

router = APIRouter(prefix="/api/config", tags=["Config"])

def _require_config_fn(name: str):
    try:
        return system_service.require_config_method(name)
    except AttributeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


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


def _require_user_uuid(request: Request) -> str:
    user_uuid = _extract_user_uuid(request)
    if not user_uuid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required for config mutations",
        )
    return user_uuid


def _config_error_detail(error: ValueError) -> str:
    message = str(error)
    prefix = "Config validation failed: "
    if message.startswith(prefix):
        detail = message[len(prefix):]
        try:
            parsed = ast.literal_eval(detail)
            if isinstance(parsed, list):
                return "\n".join(str(item) for item in parsed)
        except Exception:
            pass
        return detail
    return message


# Returns the entire config
@router.get("")
@router.get("/")
def get_full_config(request: Request):
    user_uuid = _extract_user_uuid(request)
    config = system_service.get_config(user_uuid=user_uuid)
    if not user_uuid:
        return system_service.redact_sensitive_config(config)
    return config


# Overwrites the entire config.
@router.post("")
@router.post("/")
async def overwrite_config(request: Request):
    user_uuid = _require_user_uuid(request)
    new_config = await request.json()
    save_config_fn = _require_config_fn("save_config")
    try:
        save_config_fn(new_config, user_uuid=user_uuid)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_config_error_detail(exc),
        ) from exc
    return {"status": "ok", "message": "The config has been updated."}


# Updates config
@router.patch("")
@router.patch("/")
async def update_config_bulk_route(request: Request):
    user_uuid = _require_user_uuid(request)
    updates = await request.json()
    update_bulk_fn = _require_config_fn("update_config_bulk")
    try:
        updated, failed = update_bulk_fn(updates, user_uuid=user_uuid)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_config_error_detail(exc),
        ) from exc

    return {
        "status": "partial" if failed else "ok",
        "updated": updated,
        "failed": failed,
    }


# Applies the selected preset
@router.post("/apply_preset")
async def apply_preset(request: Request):
    user_uuid = _require_user_uuid(request)
    body = await request.json()
    preset_name = body.get("name")

    if not preset_name:
        return {"status": "error", "message": "Preset name not specified"}

    apply_preset_fn = _require_config_fn("apply_preset_by_name")
    success = apply_preset_fn(preset_name, user_uuid=user_uuid)
    if success:
        return {"status": "ok", "message": f"Preset '{preset_name}' applied."}
    else:
        return {"status": "error", "message": "Preset not found"}


@router.get("/system")
def get_system_info(request: Request):
    user_uuid = _require_user_uuid(request)
    active = get_active_character_for_user(user_uuid)
    if not active:
        resolved_name = resolve_active_character_name_for_user(user_uuid, "default_waifu")
        active = set_active_character_for_user(user_uuid, char_name=resolved_name)
    char_name = (active or {}).get("name") or resolve_active_character_name_for_user(
        user_uuid,
        "default_waifu",
    )
    prompt = get_character_prompt(char_name)

    return {
        "system": {
            "active_character_id": (active or {}).get("id"),
            "char_name": char_name,
            "prompt": prompt,
            "characters": list_characters(sync_from_yaml=True),
        }
    }


@router.get("/system/characters")
def get_system_characters(request: Request):
    user_uuid = _require_user_uuid(request)
    active = get_active_character_for_user(user_uuid)
    if not active:
        resolved_name = resolve_active_character_name_for_user(user_uuid, "default_waifu")
        active = set_active_character_for_user(user_uuid, char_name=resolved_name)
    active_name = (active or {}).get("name") or resolve_active_character_name_for_user(
        user_uuid,
        "default_waifu",
    )
    return {
        "active_character_id": (active or {}).get("id"),
        "active_char_name": active_name,
        "characters": list_characters(sync_from_yaml=True),
    }


@router.post("/system/characters/import")
async def import_system_character_yaml(request: Request):
    user_uuid = _require_user_uuid(request)
    body = await request.json()
    file_name = (body.get("file_name") or body.get("name") or "").strip()
    content = body.get("content")
    set_active = bool(body.get("set_active", True))

    if not file_name:
        raise HTTPException(status_code=400, detail="file_name is required")
    if not isinstance(content, str) or not content.strip():
        raise HTTPException(status_code=400, detail="content is required")

    try:
        result = import_character_yaml_text(file_name=file_name, content=content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    imported_name = result.get("name")
    imported_prompt = get_character_prompt(imported_name)
    active = get_active_character_for_user(user_uuid)

    if set_active and imported_name:
        active = set_active_character_for_user(user_uuid, char_name=imported_name)

    return {
        "status": "ok",
        "character": {
            "name": imported_name,
            "prompt": imported_prompt,
            "prompt_length": len(imported_prompt or ""),
        },
        "active_character_id": (active or {}).get("id"),
        "active_char_name": (active or {}).get("name"),
    }


@router.post("/system/characters")
async def create_system_character(request: Request):
    user_uuid = _require_user_uuid(request)
    body = await request.json()
    name = str(body.get("name") or "").strip()
    prompt = body.get("prompt")
    set_active = bool(body.get("set_active", True))

    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    try:
        character = create_character_record(name, prompt if isinstance(prompt, str) else None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    active = get_active_character_for_user(user_uuid)
    if set_active:
        active = set_active_character_for_user(user_uuid, character_id=str(character["id"]))

    return {
        "status": "ok",
        "character": character,
        "active_character_id": (active or {}).get("id"),
        "active_char_name": (active or {}).get("name"),
    }


@router.delete("/system/characters/{character_id}")
def delete_system_character(character_id: str, request: Request):
    user_uuid = _require_user_uuid(request)
    active_before = get_active_character_for_user(user_uuid)

    try:
        deleted = delete_character_record(character_id=character_id, user_uuid=user_uuid)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    active = get_active_character_for_user(user_uuid)
    if not active and (active_before or {}).get("id") == deleted.get("id"):
        remaining = list_characters(sync_from_yaml=True)
        if remaining:
            active = set_active_character_for_user(user_uuid, character_id=str(remaining[0]["id"]))

    return {
        "status": "ok",
        "deleted": deleted,
        "active_character_id": (active or {}).get("id"),
        "active_char_name": (active or {}).get("name"),
        "characters": list_characters(sync_from_yaml=True),
    }


@router.post("/system")
async def update_system_info(request: Request):
    user_uuid = _require_user_uuid(request)
    data = await request.json()
    prompt = data.get("prompt")
    char_name = data.get("char_name")
    active_character_id = data.get("active_character_id")

    active = None
    if active_character_id:
        active = set_active_character_for_user(
            user_uuid,
            character_id=str(active_character_id),
        )
    elif char_name:
        active = set_active_character_for_user(user_uuid, char_name=str(char_name))

    if active and active.get("name"):
        char_name = str(active["name"])
    else:
        char_name = resolve_active_character_name_for_user(user_uuid, "default_waifu")

    if not char_name:
        return {"status": "error", "message": "char_name is required"}

    if prompt is not None:
        normalized_prompt = str(prompt).strip()
        if not normalized_prompt:
            return {"status": "error", "message": "prompt cannot be empty"}
        save_character_prompt(char_name, normalized_prompt)

    current_prompt = get_character_prompt(char_name)
    return {
        "status": "ok",
        "message": f"System prompt for '{char_name}' updated.",
        "system": {
            "active_character_id": (active or {}).get("id"),
            "char_name": char_name,
            "prompt": current_prompt,
        },
    }
