from fastapi import APIRouter, HTTPException, Request, status

from modules.system import auth as auth_service
from modules.system import tunnel as tunnel_service

router = APIRouter(prefix="/api/tunnel", tags=["Tunnel"])


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
            detail="Authentication required",
        )
    return user_uuid


@router.get("/status")
def tunnel_status(request: Request):
    user_uuid = _require_user_uuid(request)
    return tunnel_service.get_status(user_uuid=user_uuid)


@router.post("/start")
async def tunnel_start(request: Request):
    user_uuid = _require_user_uuid(request)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    overrides = payload if isinstance(payload, dict) else None
    return tunnel_service.start_tunnel(user_uuid=user_uuid, overrides=overrides)


@router.post("/stop")
def tunnel_stop(request: Request):
    user_uuid = _require_user_uuid(request)
    return tunnel_service.stop_tunnel(user_uuid=user_uuid)
