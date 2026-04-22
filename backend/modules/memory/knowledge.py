"""Global anchors and associative memory graph helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import uuid
from typing import Any, Dict, List, Optional, Sequence, Set

from sqlalchemy import text

from modules.database.core import engine


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_memory_knowledge_schema() -> None:
    with engine.connect() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS memory_anchors (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    anchor_key TEXT NOT NULL,
                    anchor_type TEXT NOT NULL DEFAULT 'fact',
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '[]',
                    refs TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_memory_anchors_character ON memory_anchors(character_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_memory_anchors_key ON memory_anchors(anchor_key)"
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS memory_associations (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    edge_label TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    meta TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_memory_assoc_character ON memory_associations(character_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_memory_assoc_source ON memory_associations(source_key)"
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS memory_emotion_events (
                    id TEXT PRIMARY KEY,
                    character_id TEXT NOT NULL,
                    message_id TEXT,
                    emotion TEXT NOT NULL,
                    intensity REAL NOT NULL DEFAULT 0.0,
                    trigger_text TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'runtime',
                    meta TEXT NOT NULL DEFAULT '{}',
                    occurred_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_memory_emotions_character ON memory_emotion_events(character_id)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_memory_emotions_time ON memory_emotion_events(occurred_at)"
            )
        )
        connection.commit()


def log_emotion_event(
    *,
    character_id: str,
    emotion: str,
    intensity: float = 0.0,
    trigger_text: str = "",
    source: str = "runtime",
    message_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[str] = None,
) -> Dict[str, Any]:
    ensure_memory_knowledge_schema()
    if not character_id or not str(emotion or "").strip():
        return {"status": "error"}

    event_id = str(uuid.uuid4())
    now_iso = _now_iso()
    payload = {
        "id": event_id,
        "character_id": character_id,
        "message_id": str(message_id or "").strip() or None,
        "emotion": str(emotion or "").strip().lower(),
        "intensity": float(intensity or 0.0),
        "trigger_text": str(trigger_text or "").strip(),
        "source": str(source or "runtime").strip().lower(),
        "meta": json.dumps(dict(meta or {}), ensure_ascii=False),
        "occurred_at": str(occurred_at or now_iso),
        "created_at": now_iso,
    }
    with engine.connect() as connection:
        connection.execute(
            text(
                """
                INSERT INTO memory_emotion_events (
                    id, character_id, message_id, emotion, intensity, trigger_text,
                    source, meta, occurred_at, created_at
                )
                VALUES (
                    :id, :character_id, :message_id, :emotion, :intensity, :trigger_text,
                    :source, :meta, :occurred_at, :created_at
                )
                """
            ),
            payload,
        )
        connection.commit()
    return {"status": "ok", "id": event_id}


def list_emotion_events(
    *,
    character_id: str,
    days: int = 14,
    limit: int = 100,
    emotion: str = "",
) -> List[Dict[str, Any]]:
    ensure_memory_knowledge_schema()
    if not character_id:
        return []

    safe_days = max(1, min(int(days or 14), 365))
    safe_limit = max(1, min(int(limit or 100), 500))
    threshold_dt = datetime.now(timezone.utc).timestamp() - (safe_days * 86400)
    threshold_iso = datetime.fromtimestamp(threshold_dt, tz=timezone.utc).isoformat()

    params: Dict[str, Any] = {
        "character_id": character_id,
        "threshold_iso": threshold_iso,
        "limit": safe_limit,
    }
    sql = """
        SELECT id, message_id, emotion, intensity, trigger_text, source, meta, occurred_at, created_at
        FROM memory_emotion_events
        WHERE character_id = :character_id
          AND occurred_at >= :threshold_iso
    """
    normalized_emotion = str(emotion or "").strip().lower()
    if normalized_emotion:
        sql += " AND emotion = :emotion"
        params["emotion"] = normalized_emotion
    sql += " ORDER BY occurred_at DESC LIMIT :limit"

    with engine.connect() as connection:
        rows = connection.execute(text(sql), params).fetchall()

    result: List[Dict[str, Any]] = []
    for row in rows:
        parsed_meta: Dict[str, Any] = {}
        try:
            parsed_meta = json.loads(row[6] or "{}")
        except Exception:
            parsed_meta = {}
        result.append(
            {
                "id": row[0],
                "message_id": row[1],
                "emotion": row[2],
                "intensity": float(row[3] or 0.0),
                "trigger_text": row[4] or "",
                "source": row[5] or "",
                "meta": parsed_meta,
                "occurred_at": row[7],
                "created_at": row[8],
            }
        )
    return result


def upsert_anchor(
    *,
    character_id: str,
    anchor_key: str,
    content: str,
    anchor_type: str = "fact",
    tags: Optional[Sequence[str]] = None,
    refs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_memory_knowledge_schema()
    key = (anchor_key or "").strip().lower()
    if not character_id or not key or not (content or "").strip():
        return {"status": "error"}

    now_iso = _now_iso()
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id FROM memory_anchors
                WHERE character_id = :character_id AND anchor_key = :anchor_key
                LIMIT 1
                """
            ),
            {"character_id": character_id, "anchor_key": key},
        ).fetchone()

        payload = {
            "character_id": character_id,
            "anchor_key": key,
            "anchor_type": anchor_type or "fact",
            "content": content.strip(),
            "tags": json.dumps(list(tags or []), ensure_ascii=False),
            "refs": json.dumps(dict(refs or {}), ensure_ascii=False),
            "updated_at": now_iso,
        }
        if row:
            anchor_id = str(row[0])
            payload["id"] = anchor_id
            connection.execute(
                text(
                    """
                    UPDATE memory_anchors
                    SET anchor_type = :anchor_type,
                        content = :content,
                        tags = :tags,
                        refs = :refs,
                        updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                payload,
            )
        else:
            anchor_id = str(uuid.uuid4())
            payload["id"] = anchor_id
            payload["created_at"] = now_iso
            connection.execute(
                text(
                    """
                    INSERT INTO memory_anchors (
                        id, character_id, anchor_key, anchor_type,
                        content, tags, refs, created_at, updated_at
                    )
                    VALUES (
                        :id, :character_id, :anchor_key, :anchor_type,
                        :content, :tags, :refs, :created_at, :updated_at
                    )
                    """
                ),
                payload,
            )
        connection.commit()
        return {"status": "ok", "id": anchor_id}


def list_anchors(
    *,
    character_id: str,
    query: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    ensure_memory_knowledge_schema()
    normalized_query = (query or "").strip().lower()
    sql = """
        SELECT id, anchor_key, anchor_type, content, tags, refs, created_at, updated_at
        FROM memory_anchors
        WHERE character_id = :character_id
    """
    params: Dict[str, Any] = {"character_id": character_id}
    if normalized_query:
        sql += " AND (anchor_key LIKE :q OR content LIKE :q)"
        params["q"] = f"%{normalized_query}%"
    sql += " ORDER BY updated_at DESC LIMIT :limit"
    params["limit"] = max(1, min(limit, 200))

    with engine.connect() as connection:
        rows = connection.execute(text(sql), params).fetchall()

    result: List[Dict[str, Any]] = []
    for row in rows:
        tags = []
        refs = {}
        try:
            tags = json.loads(row[4] or "[]")
        except Exception:
            tags = []
        try:
            refs = json.loads(row[5] or "{}")
        except Exception:
            refs = {}
        result.append(
            {
                "id": row[0],
                "anchor_key": row[1],
                "anchor_type": row[2],
                "content": row[3],
                "tags": tags,
                "refs": refs,
                "created_at": row[6],
                "updated_at": row[7],
            }
        )
    return result


def search_anchors(
    *,
    character_id: str,
    query_tokens: Sequence[str],
    date_keys: Sequence[str],
    limit: int = 20,
) -> List[Dict[str, Any]]:
    anchors = list_anchors(character_id=character_id, query="", limit=300)
    if not anchors:
        return []

    scored: List[Dict[str, Any]] = []
    token_set = {t.lower() for t in query_tokens if t}
    date_key_set = {d.lower() for d in date_keys if d}

    for anchor in anchors:
        key = str(anchor.get("anchor_key") or "").lower()
        content = str(anchor.get("content") or "").lower()
        tags = [str(t).lower() for t in (anchor.get("tags") or [])]
        haystack = f"{key} {content} {' '.join(tags)}"

        token_hits = sum(1 for token in token_set if token in haystack)
        date_hits = sum(1 for dk in date_key_set if dk and dk in haystack)
        if token_hits == 0 and date_hits == 0:
            continue

        score = 0.0
        if token_set:
            score += token_hits / len(token_set)
        score += date_hits * 0.75
        entry = dict(anchor)
        entry["score"] = round(score, 4)
        scored.append(entry)

    scored.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
    return scored[: max(1, min(limit, 100))]


def upsert_association(
    *,
    character_id: str,
    source_key: str,
    edge_label: str,
    target_key: str,
    weight: float = 1.0,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ensure_memory_knowledge_schema()
    source = (source_key or "").strip().lower()
    target = (target_key or "").strip().lower()
    edge = (edge_label or "related_to").strip().lower()
    if not character_id or not source or not target:
        return {"status": "error"}

    now_iso = _now_iso()
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id FROM memory_associations
                WHERE character_id = :character_id
                    AND source_key = :source_key
                    AND edge_label = :edge_label
                    AND target_key = :target_key
                LIMIT 1
                """
            ),
            {
                "character_id": character_id,
                "source_key": source,
                "edge_label": edge,
                "target_key": target,
            },
        ).fetchone()

        payload = {
            "character_id": character_id,
            "source_key": source,
            "edge_label": edge,
            "target_key": target,
            "weight": float(weight or 1.0),
            "meta": json.dumps(dict(meta or {}), ensure_ascii=False),
            "updated_at": now_iso,
        }

        if row:
            assoc_id = str(row[0])
            payload["id"] = assoc_id
            connection.execute(
                text(
                    """
                    UPDATE memory_associations
                    SET weight = :weight, meta = :meta, updated_at = :updated_at
                    WHERE id = :id
                    """
                ),
                payload,
            )
        else:
            assoc_id = str(uuid.uuid4())
            payload["id"] = assoc_id
            payload["created_at"] = now_iso
            connection.execute(
                text(
                    """
                    INSERT INTO memory_associations (
                        id, character_id, source_key, edge_label, target_key,
                        weight, meta, created_at, updated_at
                    )
                    VALUES (
                        :id, :character_id, :source_key, :edge_label, :target_key,
                        :weight, :meta, :created_at, :updated_at
                    )
                    """
                ),
                payload,
            )
        connection.commit()
        return {"status": "ok", "id": assoc_id}


def list_associations(
    *,
    character_id: str,
    query: str = "",
    limit: int = 100,
) -> List[Dict[str, Any]]:
    ensure_memory_knowledge_schema()
    normalized_query = (query or "").strip().lower()
    sql = """
        SELECT id, source_key, edge_label, target_key, weight, meta, created_at, updated_at
        FROM memory_associations
        WHERE character_id = :character_id
    """
    params: Dict[str, Any] = {"character_id": character_id}
    if normalized_query:
        sql += " AND (source_key LIKE :q OR target_key LIKE :q OR edge_label LIKE :q)"
        params["q"] = f"%{normalized_query}%"
    sql += " ORDER BY updated_at DESC LIMIT :limit"
    params["limit"] = max(1, min(limit, 300))

    with engine.connect() as connection:
        rows = connection.execute(text(sql), params).fetchall()

    result: List[Dict[str, Any]] = []
    for row in rows:
        meta = {}
        try:
            meta = json.loads(row[5] or "{}")
        except Exception:
            meta = {}
        result.append(
            {
                "id": row[0],
                "source_key": row[1],
                "edge_label": row[2],
                "target_key": row[3],
                "weight": float(row[4] or 1.0),
                "meta": meta,
                "created_at": row[6],
                "updated_at": row[7],
            }
        )
    return result


def expand_associative_terms(
    *,
    character_id: str,
    tokens: Sequence[str],
    limit: int = 8,
) -> List[Dict[str, Any]]:
    token_set: Set[str] = {str(t).strip().lower() for t in tokens if str(t).strip()}
    if not token_set:
        return []

    associations = list_associations(character_id=character_id, query="", limit=400)
    expansions: List[Dict[str, Any]] = []
    for assoc in associations:
        source = str(assoc.get("source_key") or "").lower()
        target = str(assoc.get("target_key") or "").lower()
        weight = float(assoc.get("weight") or 1.0)

        if source in token_set:
            expansions.append(
                {
                    "term": target,
                    "edge_label": assoc.get("edge_label"),
                    "weight": weight,
                    "source": source,
                }
            )
        elif target in token_set:
            expansions.append(
                {
                    "term": source,
                    "edge_label": assoc.get("edge_label"),
                    "weight": weight,
                    "source": target,
                }
            )

    expansions.sort(key=lambda item: float(item.get("weight") or 0.0), reverse=True)
    return expansions[: max(1, min(limit, 30))]
