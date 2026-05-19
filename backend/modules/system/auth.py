import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

from models.models import AuthSession, User, UserSettings
from modules.database.core import SessionLocal
from modules.system.logger import AuditStatus, log_audit_entry, log_console

PBKDF2_ITERATIONS = 210_000
DEFAULT_ACCESS_TTL_MINUTES = 60 * 24 * 365 * 10
DEFAULT_REFRESH_TTL_DAYS = 365 * 10
DEFAULT_ACCESS_TOKEN_SKEW_SECONDS = 30

_dotenv_loaded = False


@dataclass
class AuthResult:
    user: User
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    session_id: str


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _get_auth_secret() -> str:
    global _dotenv_loaded
    if not _dotenv_loaded:
        project_root = Path(__file__).resolve().parents[3]
        load_dotenv(project_root / ".env")
        _dotenv_loaded = True
    return os.getenv("AUTH_SECRET", "dev-only-change-me-auth-secret")


def _get_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except Exception:
        return default
    return max(minimum, value)


def _get_access_ttl_minutes() -> int:
    return _get_int_env("AUTH_ACCESS_TTL_MINUTES", DEFAULT_ACCESS_TTL_MINUTES, minimum=1)


def _get_refresh_ttl_days() -> int:
    return _get_int_env("AUTH_REFRESH_TTL_DAYS", DEFAULT_REFRESH_TTL_DAYS, minimum=1)


def _get_access_token_skew_seconds() -> int:
    return _get_int_env(
        "AUTH_ACCESS_TOKEN_SKEW_SECONDS",
        DEFAULT_ACCESS_TOKEN_SKEW_SECONDS,
        minimum=0,
    )


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    pad = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode((raw + pad).encode("ascii"))


def _sign_token(parts: str) -> str:
    signature = hmac.new(
        _get_auth_secret().encode("utf-8"),
        parts.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(signature)


def _encode_access_token(payload: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _b64url_encode(
        json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    payload_part = _b64url_encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_part}.{payload_part}"
    signature_part = _sign_token(signing_input)
    return f"{signing_input}.{signature_part}"


def decode_access_token(token: str) -> dict:
    if not token or token.count(".") != 2:
        raise ValueError("Invalid token format")

    header_part, payload_part, signature_part = token.split(".")
    signing_input = f"{header_part}.{payload_part}"
    expected = _sign_token(signing_input)
    if not hmac.compare_digest(expected, signature_part):
        raise ValueError("Invalid token signature")

    try:
        payload = json.loads(_b64url_decode(payload_part).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Invalid token payload") from exc

    exp = int(payload.get("exp", 0))
    now = int(_utcnow().timestamp())
    skew_seconds = _get_access_token_skew_seconds()
    if exp <= (now - skew_seconds):
        raise ValueError("Token expired")

    if payload.get("type") != "access":
        raise ValueError("Invalid token type")

    return payload


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("Password must be at least 8 characters")

    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    )
    digest = base64.b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iterations_raw, salt, digest = password_hash.split("$", 3)
    except ValueError:
        return False

    if algo != "pbkdf2_sha256":
        return False

    try:
        iterations = int(iterations_raw)
    except ValueError:
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    candidate_digest = base64.b64encode(candidate).decode("ascii")
    return hmac.compare_digest(candidate_digest, digest)


def _hash_refresh_token(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()


def _normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def _normalize_login(value: str) -> str:
    return (value or "").strip().lower()


def _trust_level_for_role(role: str) -> int:
    normalized = (role or "").strip().lower()
    if normalized == "owner":
        return 2
    if normalized == "user":
        return 1
    return 0


def _serialize_user(user: User) -> dict:
    try:
        settings = user.settings
    except Exception:
        settings = None
    return {
        "uuid": user.uuid,
        "name": user.name,
        "email": user.email,
        "login": user.login,
        "role": user.role,
        "trust_level": user.trust_level,
        "is_active": bool(user.is_active),
        "created_at": (_as_utc(user.created_at).isoformat() if user.created_at else None),
        "last_login_at": (_as_utc(user.last_login_at).isoformat() if user.last_login_at else None),
        "settings": {
            "language": getattr(settings, "language", "en-US"),
            "timezone": getattr(settings, "timezone_name", "UTC"),
            "ui_prefs": json.loads(getattr(settings, "ui_prefs", "{}") or "{}"),
        },
    }


def create_access_token(user: User, session_id: str) -> tuple[str, datetime]:
    now = _utcnow()
    exp = now + timedelta(minutes=_get_access_ttl_minutes())
    payload = {
        "sub": user.uuid,
        "sid": session_id,
        "type": "access",
        "role": user.role,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return _encode_access_token(payload), exp


def _create_refresh_session(
    session: Session,
    user: User,
    *,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> tuple[str, AuthSession]:
    refresh_token = secrets.token_urlsafe(64)
    expires_at = _utcnow() + timedelta(days=_get_refresh_ttl_days())
    db_session = AuthSession(
        id=str(uuid.uuid4()),
        user_uuid=user.uuid,
        refresh_token_hash=_hash_refresh_token(refresh_token),
        user_agent=user_agent,
        ip_address=ip_address,
        expires_at=expires_at,
    )
    session.add(db_session)
    session.flush()
    return refresh_token, db_session


def register_user(
    *,
    email: str,
    password: str,
    login: Optional[str] = None,
    name: Optional[str] = None,
    role: str = "user",
    language: str = "en-US",
    timezone_name: str = "UTC",
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> AuthResult:
    normalized_email = _normalize_email(email)
    normalized_login = _normalize_login(login or "")
    log_console(
        "Auth",
        "Производим регистрацию нового пользователя.",
        {"email": normalized_email, "login": normalized_login or None},
    )
    if "@" not in normalized_email:
        raise ValueError("Email is invalid")
    if normalized_login and len(normalized_login) < 3:
        raise ValueError("Login must be at least 3 characters")

    session: Session = SessionLocal()
    try:
        existing_auth_users = session.query(User).filter(User.password_hash.isnot(None)).count()
        log_console(
            "Auth",
            "Проверка пользователя.",
            {
                "auth_users_count": int(existing_auth_users),
                "first_registration": existing_auth_users == 0,
            },
        )
        if session.query(User).filter(User.email == normalized_email).first():
            log_console("Auth", "Пользователь уже существует.", {"email": normalized_email})
            raise ValueError("Email is already registered")
        if normalized_login and session.query(User).filter(User.login == normalized_login).first():
            log_console("Auth", "Логин уже занят.", {"login": normalized_login})
            raise ValueError("Login is already registered")

        requested_role = (role or "user").strip().lower()
        if existing_auth_users == 0:
            resolved_role = "owner"
            log_console("Auth", "Новый пользователь будет установлен как владелец.")
        else:
            resolved_role = requested_role if requested_role in {"user", "anonymous"} else "user"

        display_name = (name or "").strip() or normalized_login or normalized_email.split("@")[0]
        user = User(
            uuid=str(uuid.uuid4()),
            name=display_name,
            trust_level=_trust_level_for_role(resolved_role),
            email=normalized_email,
            login=normalized_login or None,
            password_hash=hash_password(password),
            role=resolved_role,
            auth_provider="local",
            is_active=True,
        )
        session.add(user)
        session.flush()
        log_console(
            "Auth",
            "Пользователь создан.",
            {"user_uuid": user.uuid, "role": resolved_role},
        )

        user_settings = UserSettings(
            user_uuid=user.uuid,
            language=language or "en-US",
            timezone_name=timezone_name or "UTC",
            ui_prefs="{}",
        )
        session.add(user_settings)
        log_console("Auth", "Создаем настройки пользователя по умолчанию.", {"user_uuid": user.uuid})

        refresh_token, refresh_session = _create_refresh_session(
            session,
            user,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        access_token, access_expires_at = create_access_token(user, refresh_session.id)
        user.last_login_at = _utcnow()
        refresh_expires_at = _as_utc(refresh_session.expires_at)

        session.commit()
        try:
            from modules.system import config as config_service

            log_console(
                "Auth",
                "Создаем конфигурационный файл под нового пользователя.",
                {"user_uuid": user.uuid},
            )
            config_service.ensure_user_config_exists(user.uuid)
            log_console("Auth", "Конфигурация пользователя создана.", {"user_uuid": user.uuid})
        except Exception as exc:
            log_console(
                "Auth",
                "Не удалось создать конфигурацию пользователя.",
                {"user_uuid": user.uuid, "error": str(exc)},
            )
            raise

        session.refresh(user)
        _ = user.settings
        if resolved_role == "owner":
            log_console("Auth", "Новый пользователь установлен как владелец.", {"user_uuid": user.uuid})
        log_console("Auth", "Регистрация пользователя завершена.", {"user_uuid": user.uuid})
        log_audit_entry(
            "auth_register_success",
            "[Auth] User registered.",
            AuditStatus.SUCCESS,
            details={"user_uuid": user.uuid, "email": user.email, "role": user.role},
        )
        return AuthResult(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            session_id=refresh_session.id,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def login_user(
    *,
    identity: str,
    password: str,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> AuthResult:
    normalized_identity = (identity or "").strip().lower()
    session: Session = SessionLocal()
    try:
        user = (
            session.query(User)
            .filter((User.email == normalized_identity) | (User.login == normalized_identity))
            .first()
        )
        if not user:
            raise ValueError("Invalid credentials")
        if not user.is_active:
            raise ValueError("User is inactive")
        if not user.password_hash or not verify_password(password, user.password_hash):
            raise ValueError("Invalid credentials")

        refresh_token, refresh_session = _create_refresh_session(
            session,
            user,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        access_token, access_expires_at = create_access_token(user, refresh_session.id)
        user.last_login_at = _utcnow()
        session.commit()
        session.refresh(user)
        _ = user.settings
        log_audit_entry(
            "auth_login_success",
            "[Auth] User logged in.",
            AuditStatus.SUCCESS,
            details={"user_uuid": user.uuid, "email": user.email},
        )
        return AuthResult(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=_as_utc(refresh_session.expires_at),
            session_id=refresh_session.id,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def refresh_tokens(
    *,
    refresh_token: str,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> AuthResult:
    token_hash = _hash_refresh_token(refresh_token or "")
    now = _utcnow()
    session: Session = SessionLocal()
    try:
        current_session = (
            session.query(AuthSession)
            .filter(AuthSession.refresh_token_hash == token_hash)
            .first()
        )
        if not current_session:
            raise ValueError("Invalid refresh token")
        if current_session.revoked_at is not None:
            raise ValueError("Refresh token is revoked")
        if _as_utc(current_session.expires_at) <= now:
            raise ValueError("Refresh token is expired")

        user = session.query(User).filter(User.uuid == current_session.user_uuid).first()
        if not user or not user.is_active:
            raise ValueError("User is inactive")

        current_session.revoked_at = now
        next_refresh_token, next_session = _create_refresh_session(
            session,
            user,
            user_agent=user_agent or current_session.user_agent,
            ip_address=ip_address or current_session.ip_address,
        )
        access_token, access_expires_at = create_access_token(user, next_session.id)
        user.last_login_at = now
        session.commit()
        session.refresh(user)
        _ = user.settings
        log_audit_entry(
            "auth_refresh_success",
            "[Auth] Refresh token rotated.",
            AuditStatus.INFO,
            details={"user_uuid": user.uuid, "session_id": next_session.id},
        )
        return AuthResult(
            user=user,
            access_token=access_token,
            refresh_token=next_refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=_as_utc(next_session.expires_at),
            session_id=next_session.id,
        )
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def logout(refresh_token: str) -> bool:
    token_hash = _hash_refresh_token(refresh_token or "")
    session: Session = SessionLocal()
    try:
        auth_session = (
            session.query(AuthSession)
            .filter(AuthSession.refresh_token_hash == token_hash)
            .first()
        )
        if not auth_session:
            return False
        if auth_session.revoked_at is None:
            auth_session.revoked_at = _utcnow()
            session.commit()
        log_audit_entry(
            "auth_logout",
            "[Auth] Session revoked.",
            AuditStatus.INFO,
            details={"session_id": auth_session.id, "user_uuid": auth_session.user_uuid},
        )
        return True
    except Exception:
        session.rollback()
        return False
    finally:
        session.close()


def get_user_from_access_token(token: str) -> Optional[User]:
    payload = decode_access_token(token)
    user_uuid = payload.get("sub")
    if not user_uuid:
        raise ValueError("Invalid access token payload")
    session: Session = SessionLocal()
    try:
        user = session.query(User).filter(User.uuid == user_uuid).first()
        if not user or not user.is_active:
            return None
        _ = user.settings
        return user
    finally:
        session.close()


def serialize_user(user: User) -> dict:
    return _serialize_user(user)


def get_user_by_uuid(user_uuid: str) -> Optional[User]:
    if not user_uuid:
        return None
    session: Session = SessionLocal()
    try:
        user = session.query(User).filter(User.uuid == user_uuid).first()
        if not user:
            return None
        _ = user.settings
        return user
    finally:
        session.close()


def get_auth_bootstrap_state() -> dict:
    log_console("Auth", "Проверка пользователя.")
    session: Session = SessionLocal()
    try:
        auth_users_count = (
            session.query(User)
            .filter(User.password_hash.isnot(None), User.is_active == True)
            .count()
        )
        has_owner = (
            session.query(User)
            .filter(
                User.role == "owner",
                User.password_hash.isnot(None),
                User.is_active == True,
            )
            .first()
            is not None
        )
    except (OperationalError, ProgrammingError):
        auth_users_count = 0
        has_owner = False
    finally:
        session.close()

    requires_setup = not has_owner
    log_console(
        "Auth",
        "Проверка пользователя -> найдено" if has_owner else "Проверка пользователя -> не найдено",
        {
            "has_owner": has_owner,
            "auth_users_count": int(auth_users_count),
            "requires_setup": requires_setup,
        },
    )
    return {
        "has_owner": has_owner,
        "requires_setup": requires_setup,
        "auth_users_count": int(auth_users_count),
        "first_registration_role": "owner" if requires_setup else "user",
        "allow_anonymous": has_owner,
    }
