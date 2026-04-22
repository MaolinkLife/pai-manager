from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from modules.memory.short_term import (
    ensure_short_term_schema,
    load_recent_records,
    refresh_recent_days,
)
from modules.memory.diary import (
    generate_daily_activity_entry,
    list_daily_activity_entries,
)
from modules.memory.emulator import MemorySearchEmulator
from modules.memory.knowledge import (
    ensure_memory_knowledge_schema,
    list_anchors,
    list_associations,
    list_emotion_events,
    log_emotion_event,
    upsert_anchor,
    upsert_association,
)
from models.models import History
from modules.system import character as character_service
from modules.database import service as database_service
from modules.database.core import SessionLocal
from modules.system import auth as auth_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.localization import get_text
from core.interaction import (
    resolve_interaction_policy,
)
from modules.system.service import get_active_character_name

router = APIRouter(prefix="/api/memory", tags=["Memory"])
_emulator = MemorySearchEmulator()


def _require_owner_memory_access(request: Request) -> str:
    authorization = (request.headers.get("authorization") or "").strip()
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header",
        )

    token = parts[1].strip()
    try:
        actor_user = auth_service.get_user_from_access_token(token)
    except Exception:
        actor_user = None

    actor_user_uuid = actor_user.uuid if actor_user else None
    if not actor_user_uuid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    interaction_policy = resolve_interaction_policy(actor_user_uuid)
    if not interaction_policy.can_affect_global_memory:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Memory access is not available for current role",
        )
    return actor_user_uuid or ""


def _normalize_utc_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = value.isoformat() if hasattr(value, "isoformat") else str(value)
    if not raw:
        return None
    if raw.endswith("Z") or "+" in raw[10:] or "-" in raw[10:]:
        return raw
    if "T" in raw:
        return f"{raw}Z"
    return raw


def _safe_lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_day(value: Optional[str]) -> Optional[date]:
    text_raw = str(value or "").strip()
    if not text_raw:
        return None
    try:
        return date.fromisoformat(text_raw)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid date format. Use YYYY-MM-DD.",
        )


def _score_record(
    record_summary: str, themes: List[str], dialogue_ids: List[str], query: str
) -> tuple[float, List[str]]:
    normalized_query = _safe_lower(query)
    if not normalized_query:
        return 0.0, []

    reasons: List[str] = []
    haystack = " ".join(
        [record_summary or "", " ".join(themes or []), " ".join(dialogue_ids or [])]
    ).lower()

    score = 0.0
    if normalized_query in haystack:
        score += 1.0
        reasons.append("substring")

    query_tokens = [token for token in normalized_query.split() if token]
    if query_tokens:
        matched_tokens = sum(1 for token in query_tokens if token in haystack)
        if matched_tokens > 0:
            score += matched_tokens / len(query_tokens)
            reasons.append(f"token_match:{matched_tokens}/{len(query_tokens)}")

    return score, reasons


def _load_message_preview(dialogue_ids: List[str], max_items: int = 3) -> List[Dict[str, Any]]:
    if not dialogue_ids:
        return []

    session: Session = SessionLocal()
    try:
        rows = (
            session.query(History)
            .filter(History.id.in_(dialogue_ids))
            .order_by(History.timestamp.desc())
            .limit(max_items)
            .all()
        )
        return [
            {
                "id": row.id,
                "role": row.role,
                "content": row.content,
                "timestamp": _normalize_utc_iso(row.timestamp),
            }
            for row in rows
        ]
    finally:
        session.close()


@router.post("/refresh")
async def refresh_short_term_memory(
    request: Request, days: int = Query(default=7, ge=1, le=60)
) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    print(
        get_text(
            "memory_routes.refresh_request",
            default="[MemoryRoutes] Запрос на обновление краткосрочной памяти через API.",
        )
    )
    ensure_short_term_schema()
    ensure_memory_knowledge_schema()

    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )

    character = character_service.get_or_create_character(char_name)
    refresh_recent_days(character.id, days=days)
    records = load_recent_records(days=days)

    log_audit_entry(
        "memory_route_refresh",
        get_text(
            "memory_routes.refresh_completed",
            default="[MemoryRoutes] Выполнено обновление краткосрочной памяти.",
        ),
        status=AuditStatus.INFO,
        details={"records": len(records)},
        message_key="memory_routes.refresh_completed",
    )
    return {"status": "ok", "records": len(records), "days": days}


@router.get("/short-term")
async def list_short_term_memory(
    request: Request, days: int = Query(default=7, ge=1, le=120)
) -> dict:
    _require_owner_memory_access(request)
    print(
        get_text(
            "memory_routes.list_request",
            default="[MemoryRoutes] Получение записей краткосрочной памяти через API.",
        )
    )
    ensure_short_term_schema()
    ensure_memory_knowledge_schema()
    records = load_recent_records(days=days)
    payload = []
    for record in records:
        payload.append(
            {
                "id": record.id,
                "summary": record.summary,
                "dialogue_ids": record.dialogue_ids,
                "themes": record.themes,
                "created_at": _normalize_utc_iso(record.created_at),
                "updated_at": _normalize_utc_iso(record.updated_at),
            }
        )

    log_audit_entry(
        "memory_route_list",
        get_text(
            "memory_routes.list_return",
            default="[MemoryRoutes] Возвращаем список записей краткосрочной памяти.",
        ),
        status=AuditStatus.INFO,
        details={"records": len(payload)},
        message_key="memory_routes.list_return",
    )
    return {"records": payload, "total": len(payload), "days": days}


@router.get("/search")
async def search_short_term_memory(
    request: Request,
    q: Optional[str] = Query(default=None),
    message_id: Optional[str] = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    _require_owner_memory_access(request)
    ensure_short_term_schema()
    ensure_memory_knowledge_schema()
    records = load_recent_records(days=days)

    normalized_query = _safe_lower(q)
    normalized_message_id = (message_id or "").strip()

    payload: List[Dict[str, Any]] = []
    for record in records:
        reasons: List[str] = []
        score = 0.0

        if normalized_message_id and normalized_message_id in (record.dialogue_ids or []):
            score += 3.0
            reasons.append("message_id")

        if normalized_query:
            query_score, query_reasons = _score_record(
                record.summary, record.themes, record.dialogue_ids, normalized_query
            )
            score += query_score
            reasons.extend(query_reasons)

        if normalized_query or normalized_message_id:
            if score <= 0:
                continue
        else:
            score = 0.1
            reasons.append("default_recent")

        payload.append(
            {
                "id": record.id,
                "summary": record.summary,
                "dialogue_ids": record.dialogue_ids,
                "themes": record.themes,
                "created_at": _normalize_utc_iso(record.created_at),
                "updated_at": _normalize_utc_iso(record.updated_at),
                "score": round(score, 4),
                "match_reasons": reasons,
                "message_preview": _load_message_preview(record.dialogue_ids, max_items=3),
            }
        )

    payload.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            item.get("updated_at") or "",
        ),
        reverse=True,
    )
    sliced = payload[:limit]

    return {
        "records": sliced,
        "total": len(sliced),
        "query": normalized_query,
        "message_id": normalized_message_id or None,
        "days": days,
        "generated_at": _normalize_utc_iso(datetime.utcnow()),
    }


@router.get("/emulate-search")
async def emulate_memory_search(
    request: Request,
    q: str = Query(default=""),
    message_id: Optional[str] = Query(default=None),
    recent_pairs: int = Query(default=32, ge=1, le=200),
    window_pairs: int = Query(default=32, ge=1, le=200),
    lookback_days: int = Query(default=7, ge=1, le=365),
    top_k: int = Query(default=8, ge=1, le=50),
) -> dict:
    _require_owner_memory_access(request)
    ensure_short_term_schema()
    ensure_memory_knowledge_schema()
    return _emulator.emulate(
        query=q,
        message_id=message_id,
        recent_pairs=recent_pairs,
        window_pairs=window_pairs,
        lookback_days=lookback_days,
        top_k=top_k,
    )


@router.get("/history")
async def list_full_history(
    request: Request,
    limit: int = Query(default=32, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    rows = database_service.get_history(char_name, limit=limit + 1, offset=offset) or []
    has_more = len(rows) > limit
    records = rows[:limit]
    return {
        "status": "success",
        "records": [
            {
                "id": item.get("id"),
                "role": item.get("role"),
                "content": item.get("content"),
                "timestamp": item.get("timestamp"),
            }
            for item in records
        ],
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }


@router.get("/diary")
async def list_diary_entries(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    character = character_service.get_or_create_character(char_name)
    entries = list_daily_activity_entries(character_id=character.id, days=days)
    return {
        "status": "ok",
        "entries": [entry.to_dict() for entry in entries],
        "total": len(entries),
        "days": days,
    }


@router.post("/diary/generate")
async def generate_diary_entry(
    request: Request,
    day: Optional[str] = Query(default=None),
    force: bool = Query(default=False),
) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    character = character_service.get_or_create_character(char_name)
    target_day = _parse_day(day)
    result = generate_daily_activity_entry(
        character_id=character.id,
        target_day=target_day,
        force=bool(force),
    )
    return {
        "status": "ok",
        **result,
    }


@router.get("/anchors")
async def get_memory_anchors(
    request: Request,
    query: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=300),
) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    ensure_memory_knowledge_schema()
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    character = character_service.get_or_create_character(char_name)
    anchors = list_anchors(character_id=character.id, query=query, limit=limit)
    return {"status": "success", "anchors": anchors, "total": len(anchors)}


@router.post("/anchors")
async def create_or_update_anchor(request: Request, payload: Dict[str, Any]) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    ensure_memory_knowledge_schema()
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    character = character_service.get_or_create_character(char_name)
    result = upsert_anchor(
        character_id=character.id,
        anchor_key=str(payload.get("anchor_key") or ""),
        anchor_type=str(payload.get("anchor_type") or "fact"),
        content=str(payload.get("content") or ""),
        tags=payload.get("tags") if isinstance(payload.get("tags"), list) else [],
        refs=payload.get("refs") if isinstance(payload.get("refs"), dict) else {},
    )
    return result


@router.get("/associations")
async def get_memory_associations(
    request: Request,
    query: str = Query(default=""),
    limit: int = Query(default=100, ge=1, le=300),
) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    ensure_memory_knowledge_schema()
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    character = character_service.get_or_create_character(char_name)
    items = list_associations(character_id=character.id, query=query, limit=limit)
    return {"status": "success", "associations": items, "total": len(items)}


@router.post("/associations")
async def create_or_update_association(
    request: Request, payload: Dict[str, Any]
) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    ensure_memory_knowledge_schema()
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    character = character_service.get_or_create_character(char_name)
    return upsert_association(
        character_id=character.id,
        source_key=str(payload.get("source_key") or ""),
        edge_label=str(payload.get("edge_label") or "related_to"),
        target_key=str(payload.get("target_key") or ""),
        weight=float(payload.get("weight") or 1.0),
        meta=payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
    )


@router.get("/emotions")
async def get_emotion_events(
    request: Request,
    days: int = Query(default=14, ge=1, le=365),
    limit: int = Query(default=100, ge=1, le=500),
    emotion: str = Query(default=""),
) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    ensure_memory_knowledge_schema()
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    character = character_service.get_or_create_character(char_name)
    items = list_emotion_events(
        character_id=character.id,
        days=days,
        limit=limit,
        emotion=emotion,
    )
    return {"status": "success", "events": items, "total": len(items)}


@router.post("/emotions")
async def create_emotion_event(request: Request, payload: Dict[str, Any]) -> dict:
    actor_user_uuid = _require_owner_memory_access(request)
    ensure_memory_knowledge_schema()
    char_name = get_active_character_name(
        user_uuid=actor_user_uuid,
        default="default_waifu",
    )
    character = character_service.get_or_create_character(char_name)
    return log_emotion_event(
        character_id=character.id,
        message_id=str(payload.get("message_id") or "").strip() or None,
        emotion=str(payload.get("emotion") or ""),
        intensity=float(payload.get("intensity") or 0.0),
        trigger_text=str(payload.get("trigger_text") or ""),
        source=str(payload.get("source") or "manual"),
        meta=payload.get("meta") if isinstance(payload.get("meta"), dict) else {},
        occurred_at=str(payload.get("occurred_at") or "").strip() or None,
    )

