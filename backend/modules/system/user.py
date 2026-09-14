import uuid
from typing import Optional

from sqlalchemy.orm import Session

from models.models import User, UserSettings
from modules.database.core import SessionLocal


def get_or_create_user(name: str, trust_level: int = 0):
    session: Session = SessionLocal()
    try:
        user = session.query(User).filter_by(name=name).first()
        if user:
            return user

        new_user = User(uuid=str(uuid.uuid4()), name=name, trust_level=trust_level)
        session.add(new_user)
        session.commit()
        session.refresh(new_user)
        return new_user
    finally:
        session.close()


def get_owner():
    session: Session = SessionLocal()
    try:
        return session.query(User).filter_by(trust_level=2).first()
    finally:
        session.close()


def resolve_owner_timezone() -> Optional[str]:
    """IANA timezone of the owner (UserSettings.timezone_name, set from the
    browser at registration). None when there is no owner or the stored name is
    not a valid zone. Never raises."""
    try:
        from zoneinfo import ZoneInfo

        session: Session = SessionLocal()
        try:
            row = (
                session.query(UserSettings.timezone_name)
                .join(User, User.uuid == UserSettings.user_uuid)
                .filter(User.role == "owner", User.is_active.is_(True))
                .order_by(User.last_login_at.desc())
                .first()
            )
        finally:
            session.close()
        zone_name = str((row[0] if row else "") or "").strip()
        if not zone_name:
            return None
        ZoneInfo(zone_name)
        return zone_name
    except Exception:
        return None


def resolve_user_language(
    *,
    user_uuid: Optional[str] = None,
    character_id: Optional[str] = None,
    fallback: str = "en-US",
) -> str:
    """Source of truth for the language PAI generates in.

    Order:
      1. UserSettings.language for the given user_uuid.
      2. UserSettings.language for the user whose active_character_id matches.
      3. system.language from DB-config (UI/locale fallback).
      4. The static `fallback`.

    Never raises — DB errors degrade to fallback.
    """
    try:
        session: Session = SessionLocal()
        try:
            settings = None
            if user_uuid:
                settings = (
                    session.query(UserSettings).filter_by(user_uuid=user_uuid).first()
                )
            if settings is None and character_id:
                settings = (
                    session.query(UserSettings)
                    .filter(UserSettings.active_character_id == character_id)
                    .first()
                )
            lang = str(getattr(settings, "language", "") or "").strip()
            if lang:
                return lang
        finally:
            session.close()
    except Exception:
        pass

    try:
        from modules.system import config as config_service

        system_lang = str(
            config_service.get_config_value("system.language", "") or ""
        ).strip()
        if system_lang:
            return system_lang
    except Exception:
        pass

    return fallback
