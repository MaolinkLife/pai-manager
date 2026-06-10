from datetime import timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

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


@router.get("/bootstrap-state")
async def bootstrap_state():
    return auth_service.get_auth_bootstrap_state()
