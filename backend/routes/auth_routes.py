from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from core import ws_tickets
from modules.system import auth as auth_service

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class RegisterRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    login: Optional[str] = None
    name: Optional[str] = None
    role: str = "user"
    language: str = "en-US"
    timezone: str = "UTC"


class LoginRequest(BaseModel):
    identity: str
    password: str = Field(min_length=8)


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


def _extract_client_ip(request: Request) -> Optional[str]:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client and request.client.host:
        return request.client.host
    return None


def _token_response(result: auth_service.AuthResult) -> dict:
    access_exp = (
        result.access_expires_at.astimezone(timezone.utc).isoformat()
        if result.access_expires_at
        else None
    )
    refresh_exp = (
        result.refresh_expires_at.astimezone(timezone.utc).isoformat()
        if result.refresh_expires_at
        else None
    )
    return {
        "token_type": "Bearer",
        "access_token": result.access_token,
        "refresh_token": result.refresh_token,
        "access_expires_at": access_exp,
        "refresh_expires_at": refresh_exp,
        "session_id": result.session_id,
        "user": auth_service.serialize_user(result.user),
    }


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is missing",
        )
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be Bearer token",
        )
    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is missing",
        )
    return token


def _owner_session(authorization: Optional[str], forbidden_detail: str) -> tuple:
    """The signed-in owner and the id of the session that asks; 401 or 403 otherwise."""
    token = _extract_bearer_token(authorization)
    try:
        user = auth_service.get_user_from_access_token(token)
        session_id = auth_service.decode_access_token(token).get("sid")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    if (user.role or "").strip().lower() != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=forbidden_detail)
    return user, session_id


@router.post("/register")
async def register(payload: RegisterRequest, request: Request):
    try:
        result = auth_service.register_user(
            email=payload.email,
            password=payload.password,
            login=payload.login,
            name=payload.name,
            role=payload.role,
            language=payload.language,
            timezone_name=payload.timezone,
            user_agent=request.headers.get("user-agent"),
            ip_address=_extract_client_ip(request),
        )
        return _token_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    try:
        result = auth_service.login_user(
            identity=payload.identity,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            ip_address=_extract_client_ip(request),
        )
        return _token_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post("/refresh")
async def refresh(payload: RefreshRequest, request: Request):
    try:
        result = auth_service.refresh_tokens(
            refresh_token=payload.refresh_token,
            user_agent=request.headers.get("user-agent"),
            ip_address=_extract_client_ip(request),
        )
        return _token_response(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post("/logout")
async def logout(payload: LogoutRequest):
    revoked = auth_service.logout(payload.refresh_token)
    return {"status": "ok" if revoked else "not_found", "revoked": revoked}


@router.get("/me")
async def me(authorization: Optional[str] = Header(default=None)):
    token = _extract_bearer_token(authorization)
    try:
        user = auth_service.get_user_from_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return {"user": auth_service.serialize_user(user)}


@router.post("/ws-ticket")
async def issue_ws_ticket(authorization: Optional[str] = Header(default=None)):
    """A one-time pass for opening the chat WebSocket (core.ws_tickets).

    The access token comes in the header here, so it never has to appear in the
    socket's address.
    """
    token = _extract_bearer_token(authorization)
    try:
        user = auth_service.get_user_from_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    return {"ticket": ws_tickets.store.issue(user.uuid), "expires_in": ws_tickets.store.ttl_seconds}


class UpdateMeSettingsRequest(BaseModel):
    language: Optional[str] = None
    timezone: Optional[str] = None


@router.patch("/me/settings")
async def update_me_settings(
    payload: UpdateMeSettingsRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Update UserSettings fields for the current authenticated user.

    Currently exposes ``language`` (generation language — source of truth
    for resolve_user_language) and ``timezone``. UI prefs go through other
    endpoints. Other fields stay immutable to avoid accidental ownership
    confusion.
    """
    token = _extract_bearer_token(authorization)
    try:
        user = auth_service.get_user_from_access_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    try:
        auth_service.update_user_settings(
            user.uuid,
            language=payload.language,
            timezone=payload.timezone,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    refreshed = auth_service.get_user_from_access_token(token)
    return {"user": auth_service.serialize_user(refreshed)} if refreshed else {"user": None}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


@router.post("/me/password")
async def change_my_password(
    payload: ChangePasswordRequest,
    authorization: Optional[str] = Header(default=None),
):
    """Change the signed-in owner's password; the owner's other sessions are signed out.

    Owner only for now: `user` accounts get it when guests are wired in.
    """
    user, session_id = _owner_session(authorization, "Only the owner can change the password here")
    try:
        revoked = auth_service.change_password(
            user.uuid,
            current_password=payload.current_password,
            new_password=payload.new_password,
            keep_session_id=session_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"status": "ok", "revoked_sessions": revoked}


@router.get("/me/sessions")
async def list_my_sessions(authorization: Optional[str] = Header(default=None)):
    """The devices signed in to the owner account; the one that asks is marked current."""
    user, session_id = _owner_session(authorization, "Only the owner can see the devices here")
    sessions = auth_service.list_active_sessions(user.uuid)
    return {"sessions": [{**item, "current": item["id"] == session_id} for item in sessions]}


@router.post("/me/sessions/revoke-others")
async def revoke_my_other_sessions(authorization: Optional[str] = Header(default=None)):
    """Sign out every other device; the one that asks stays signed in."""
    user, session_id = _owner_session(authorization, "Only the owner can sign out the devices here")
    revoked = auth_service.revoke_other_sessions(user.uuid, keep_session_id=session_id)
    return {"status": "ok", "revoked_sessions": revoked}


@router.post("/me/sessions/{target_session_id}/revoke")
async def revoke_my_session(target_session_id: str, authorization: Optional[str] = Header(default=None)):
    """Sign out one other device. The device that asks signs out through /logout."""
    user, session_id = _owner_session(authorization, "Only the owner can sign out the devices here")
    if target_session_id == session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This device signs out through logout",
        )
    if not auth_service.revoke_session(user.uuid, target_session_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such signed-in device")
    return {"status": "ok"}


@router.get("/bootstrap-state")
async def bootstrap_state():
    return auth_service.get_auth_bootstrap_state()
