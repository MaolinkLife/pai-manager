from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict
import re
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request

from modules.system.service import get_active_character_name
from modules.moral_matrix.repository import MoralMatrixRepository
from modules.system.character import get_or_create_character
from modules.system import auth as auth_service

router = APIRouter(prefix="/api/moral", tags=["Moral Matrix"])

_repository = MoralMatrixRepository()


def _safe_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _extract_user_timezone(request: Request) -> str:
    explicit_tz = (request.headers.get("X-Client-Timezone") or "").strip()
    if explicit_tz:
        return explicit_tz

    authorization = request.headers.get("Authorization") or ""
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1]:
        try:
            user = auth_service.get_user_from_access_token(parts[1].strip())
            timezone_name = getattr(getattr(user, "settings", None), "timezone_name", None)
            if isinstance(timezone_name, str) and timezone_name.strip():
                return timezone_name.strip()
        except Exception:
            pass
    return "UTC"


def _extract_user_uuid(request: Request) -> str | None:
    authorization = request.headers.get("Authorization") or ""
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    try:
        user = auth_service.get_user_from_access_token(parts[1].strip())
    except Exception:
        return None
    return user.uuid if user else None


def _normalize_to_tz_iso(value: Any, timezone_name: str) -> str | None:
    if value is None:
        return None

    raw = value.isoformat() if hasattr(value, "isoformat") else str(value)
    if not raw:
        return None

    if "T" not in raw:
        return raw

    candidate = raw
    has_timezone = bool(re.search(r"([zZ]|[+\-]\d{2}:\d{2})$", candidate))
    if not has_timezone:
        candidate = f"{candidate}+00:00"
    elif candidate.endswith("Z") or candidate.endswith("z"):
        candidate = f"{candidate[:-1]}+00:00"

    try:
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        tz = ZoneInfo(timezone_name or "UTC")
        return dt.astimezone(tz).isoformat()
    except Exception:
        return raw


@router.get("/state")
async def get_moral_state(
    request: Request,
    limit: int = Query(default=12, ge=1, le=100),
) -> Dict[str, Any]:
    try:
        character_name = get_active_character_name(
            user_uuid=_extract_user_uuid(request),
            default="default_waifu",
        )
        character = get_or_create_character(character_name)
    except Exception:
        return {
            "status": "degraded",
            "character": {"id": None, "name": "default_waifu"},
            "state": {
                "trust": 0.5,
                "stability": 0.5,
                "sociability": 0.5,
                "resentment": 0.0,
                "current_emotion": "peace",
                "emotion_intensity": 0.0,
                "emotion_vector": {},
                "trigger": "moral state unavailable",
                "associated_events": [],
                "influence": {},
                "affective_state": {},
                "updated_at": None,
            },
            "latest_snapshot": {},
            "daily_summary": {},
            "recent_traces": [],
        }
    user_timezone = _extract_user_timezone(request)

    snapshot = _repository.fetch_latest_snapshot(character.id) or {}
    daily_summary = _repository.fetch_daily_summary(character.id, date.today()) or {}
    recent_traces = _repository.fetch_recent_traces(character.id, limit=limit)
    latest_trace = recent_traces[0] if recent_traces else {}

    emotion_vector = (
        latest_trace.get("emotion_vector")
        or daily_summary.get("emotion_vector")
        or {}
    )

    state = {
        "trust": _safe_float(snapshot.get("trust"), _safe_float(daily_summary.get("trust"), 0.5)),
        "stability": _safe_float(
            snapshot.get("stability"), _safe_float(daily_summary.get("stability"), 0.5)
        ),
        "sociability": _safe_float(
            snapshot.get("sociability"), _safe_float(daily_summary.get("sociability"), 0.5)
        ),
        "resentment": _safe_float(
            snapshot.get("resentment"), _safe_float(daily_summary.get("resentment"), 0.0)
        ),
        "current_emotion": latest_trace.get("primary_emotion")
        or snapshot.get("mood")
        or daily_summary.get("dominant_emotion")
        or "neutral",
        "emotion_intensity": _safe_float(
            latest_trace.get("intensity"), _safe_float(daily_summary.get("average_intensity"), 0.0)
        ),
        "emotion_vector": emotion_vector,
        "trigger": (latest_trace.get("notes") or {}).get("affective_state", {}).get("trigger")
        if isinstance(latest_trace.get("notes"), dict)
        else None,
        "associated_events": (latest_trace.get("notes") or {}).get("affective_state", {}).get("associated_events", [])
        if isinstance(latest_trace.get("notes"), dict)
        else [],
        "influence": (latest_trace.get("notes") or {}).get("affective_state", {}).get("influence", {})
        if isinstance(latest_trace.get("notes"), dict)
        else {},
        "affective_state": (latest_trace.get("notes") or {}).get("affective_state")
        if isinstance(latest_trace.get("notes"), dict)
        else (snapshot.get("meta") or {}).get("affective_state")
        if isinstance(snapshot.get("meta"), dict)
        else {},
        "updated_at": _normalize_to_tz_iso(
            latest_trace.get("created_at")
            or snapshot.get("created_at")
            or daily_summary.get("updated_at")
            or daily_summary.get("created_at"),
            user_timezone,
        ),
    }

    return {
        "status": "success",
        "character": {"id": character.id, "name": character.name},
        "state": state,
        "latest_snapshot": snapshot,
        "daily_summary": daily_summary,
        "recent_traces": recent_traces,
    }

