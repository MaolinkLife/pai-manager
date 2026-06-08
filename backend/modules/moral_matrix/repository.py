"""Database access helpers for the MoralMatrix module."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pprint import pformat
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from models.models import (
    DailyMoralSummary,
    EmotionalTrace,
    MoralStateSnapshot,
)
from modules.database.core import SessionLocal
from modules.system.logger import AuditStatus, log_audit_entry


@dataclass
class RepositoryConfig:
    session_factory: Any = SessionLocal


class MoralMatrixRepository:
    """Thin CRUD wrapper around SQLAlchemy models used by the MoralMatrix."""

    def __init__(self, config: RepositoryConfig | None = None) -> None:
        cfg = config or RepositoryConfig()
        self._session_factory = cfg.session_factory

    @contextmanager
    def _session(self) -> Iterable[Session]:
        session: Session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # ------------------------------------------------------------------ #
    # Fetch helpers
    # ------------------------------------------------------------------ #
    def fetch_traces_for_messages(
        self, character_id: str, message_ids: Sequence[str]
    ) -> List[Dict[str, Any]]:
        if not message_ids:
            return []
        with self._session() as session:
            rows = (
                session.query(EmotionalTrace)
                .filter(
                    EmotionalTrace.character_id == character_id,
                    EmotionalTrace.message_id.in_(list(message_ids)),
                )
                .order_by(EmotionalTrace.created_at.desc())
                .all()
            )
            return [self._serialize_trace(row) for row in rows]

    def fetch_recent_traces(
        self, character_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        with self._session() as session:
            rows = (
                session.query(EmotionalTrace)
                .filter(EmotionalTrace.character_id == character_id)
                .order_by(EmotionalTrace.created_at.desc())
                .limit(limit)
                .all()
            )
            return [self._serialize_trace(row) for row in rows]

    def fetch_similar_traces(
        self,
        character_id: str,
        query_text: str,
        *,
        limit: int = 5,
        scan_limit: int = 160,
    ) -> List[Dict[str, Any]]:
        terms = self._tokenize(query_text)
        if not character_id or not terms:
            return []
        with self._session() as session:
            rows = (
                session.query(EmotionalTrace)
                .filter(EmotionalTrace.character_id == character_id)
                .order_by(EmotionalTrace.created_at.desc())
                .limit(scan_limit)
                .all()
            )
            scored: list[tuple[float, Dict[str, Any]]] = []
            for row in rows:
                item = self._serialize_trace(row)
                haystack = " ".join(
                    str(part or "")
                    for part in [
                        item.get("cause"),
                        item.get("primary_emotion"),
                        item.get("secondary_emotion"),
                        item.get("user_tone"),
                        item.get("notes"),
                    ]
                )
                hay_terms = self._tokenize(haystack)
                if not hay_terms:
                    continue
                overlap = terms.intersection(hay_terms)
                if not overlap:
                    continue
                score = len(overlap) / max(len(terms), 1)
                item["similarity_score"] = round(score, 4)
                scored.append((score, item))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            return [item for _, item in scored[:limit]]

    def fetch_latest_snapshot(self, character_id: str) -> Optional[Dict[str, Any]]:
        with self._session() as session:
            row = (
                session.query(MoralStateSnapshot)
                .filter(MoralStateSnapshot.character_id == character_id)
                .order_by(MoralStateSnapshot.created_at.desc())
                .first()
            )
            return self._serialize_snapshot(row) if row else None

    def fetch_daily_summary(
        self, character_id: str, summary_date: date | None = None
    ) -> Optional[Dict[str, Any]]:
        target_date = summary_date or date.today()
        with self._session() as session:
            row = (
                session.query(DailyMoralSummary)
                .filter(
                    DailyMoralSummary.character_id == character_id,
                    DailyMoralSummary.date == target_date,
                )
                .order_by(DailyMoralSummary.updated_at.desc())
                .first()
            )
            return self._serialize_daily_summary(row) if row else None

    # ------------------------------------------------------------------ #
    # Mutations
    # ------------------------------------------------------------------ #
    def store_snapshot(
        self,
        character_id: str,
        message_id: Optional[str],
        payload: Dict[str, Any],
    ) -> Optional[str]:
        if not character_id:
            return None
        with self._session() as session:
            snapshot = MoralStateSnapshot(
                character_id=character_id,
                message_id=message_id,
                trust=float(payload.get("trust", 0.6)),
                stability=float(payload.get("stability", 0.6)),
                sociability=float(payload.get("sociability", 0.6)),
                resentment=float(payload.get("resentment", 0.05)),
                mood=payload.get("current_emotion", "neutral"),
                recommendations=json.dumps(
                    payload.get("recommendations", []), ensure_ascii=False
                ),
                hard_directives=json.dumps(
                    payload.get("hard_directives", []), ensure_ascii=False
                ),
                meta=json.dumps(payload.get("meta", {}), ensure_ascii=False),
            )
            session.add(snapshot)
            session.commit()
            session.refresh(snapshot)
            log_audit_entry(
                "moral_matrix_snapshot_saved",
                "[MoralMatrix] Snapshot persisted.",
                AuditStatus.SUCCESS,
                details={
                    "snapshot_id": snapshot.id,
                    "character_id": character_id,
                    "message_id": message_id,
                    "payload": payload,
                },
            )
            print(f"[MoralMatrix] Snapshot saved id: {snapshot.id}")
            return snapshot.id

    def store_emotional_trace(
        self,
        character_id: str,
        *,
        message_id: Optional[str],
        payload: Dict[str, Any],
    ) -> Optional[str]:
        if not character_id:
            return None
        with self._session() as session:
            trace = EmotionalTrace(
                character_id=character_id,
                message_id=message_id,
                trigger_role=payload.get("trigger_role", "assistant"),
                primary_emotion=payload.get("primary_emotion", "neutral"),
                secondary_emotion=payload.get("secondary_emotion"),
                intensity=float(payload.get("intensity", 0.0)),
                emotion_vector=json.dumps(
                    payload.get("emotion_vector", {}), ensure_ascii=False
                ),
                user_tone=payload.get("user_tone"),
                cause=payload.get("cause"),
                notes=(
                    json.dumps(payload.get("notes"), ensure_ascii=False)
                    if isinstance(payload.get("notes"), (dict, list))
                    else payload.get("notes")
                ),
            )
            session.add(trace)
            session.commit()
            session.refresh(trace)
            log_audit_entry(
                "moral_matrix_trace_saved",
                "[MoralMatrix] Emotional trace persisted.",
                AuditStatus.SUCCESS,
                details={
                    "trace_id": trace.id,
                    "character_id": character_id,
                    "message_id": message_id,
                    "primary": payload.get("primary_emotion"),
                    "intensity": payload.get("intensity"),
                },
            )
            print(
                f"[MoralMatrix] Trace saved id: {trace.id} ",
            )
            return trace.id

    def decay_emotional_traces(
        self,
        character_id: str,
        *,
        global_rate: float = 0.05,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Apply daily decay to every unresolved trace for ``character_id``.

        Per row: ``new_intensity = max(persistence_floor,
            intensity - effective_rate * days_elapsed)`` where ``effective_rate``
        comes from the row's own ``decay_rate`` (falling back to ``global_rate``
        when the row hasn't been migrated yet).

        ``days_elapsed`` is measured from ``last_decayed_at`` (or ``created_at``
        if the worker never touched this row yet). Always >= 0, so running the
        job twice on the same day is idempotent.
        """
        if not character_id:
            return {"updated": 0, "skipped": 0}

        now = now or datetime.now(timezone.utc)
        updated = 0
        floored = 0
        skipped_no_age = 0

        with self._session() as session:
            from models.models import EmotionalTrace  # local import to avoid cycles

            rows = (
                session.query(EmotionalTrace)
                .filter(
                    EmotionalTrace.character_id == character_id,
                    EmotionalTrace.resolved.is_(False) | EmotionalTrace.resolved.is_(None),
                )
                .all()
            )

            for row in rows:
                base_time = row.last_decayed_at or row.created_at
                if base_time is None:
                    skipped_no_age += 1
                    continue
                if base_time.tzinfo is None:
                    base_time = base_time.replace(tzinfo=timezone.utc)

                days_elapsed = max(0.0, (now - base_time).total_seconds() / 86400.0)
                # Decay has daily granularity. Running the worker twice in the
                # same calendar window must be idempotent — clock skew of a
                # few seconds shouldn't move the value.
                if days_elapsed < 1.0:
                    continue

                effective_rate = float(row.decay_rate or global_rate)
                floor = float(row.persistence_floor or 0.0)
                current = float(row.intensity or 0.0)
                new_intensity = current - effective_rate * days_elapsed
                if new_intensity < floor:
                    new_intensity = floor
                    if current > floor:
                        floored += 1

                if abs(new_intensity - current) < 1e-9:
                    # Already at floor and no further movement — still bump
                    # last_decayed_at so we don't repeatedly scan this row.
                    row.last_decayed_at = now
                    continue

                row.intensity = new_intensity
                row.last_decayed_at = now
                updated += 1

            session.commit()

        return {
            "updated": updated,
            "floored": floored,
            "skipped_no_age": skipped_no_age,
            "scanned": len(rows),
        }

    def annotate_previous_trace_outcome(
        self,
        character_id: str,
        *,
        current_message_id: Optional[str],
        payload: Dict[str, Any],
    ) -> Optional[str]:
        if not character_id:
            return None
        with self._session() as session:
            query = session.query(EmotionalTrace).filter(
                EmotionalTrace.character_id == character_id
            )
            if current_message_id:
                query = query.filter(EmotionalTrace.message_id != current_message_id)
            trace = query.order_by(EmotionalTrace.created_at.desc()).first()
            if not trace:
                return None
            notes = self._parse_json_or_text(trace.notes)
            if not isinstance(notes, dict):
                notes = {"raw": notes} if notes else {}
            outcomes = notes.get("outcomes")
            if not isinstance(outcomes, list):
                outcomes = []
            outcomes.append(payload)
            notes["outcomes"] = outcomes[-6:]
            trace.notes = json.dumps(notes, ensure_ascii=False)
            session.commit()
            log_audit_entry(
                "moral_matrix_trace_outcome_saved",
                "[MoralMatrix] Previous emotional trace outcome updated.",
                AuditStatus.SUCCESS,
                details={
                    "trace_id": trace.id,
                    "character_id": character_id,
                    "current_message_id": current_message_id,
                    "outcome": payload,
                },
            )
            return trace.id

    # ------------------------------------------------------------------ #
    # Serialization helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _serialize_trace(row: EmotionalTrace) -> Dict[str, Any]:
        try:
            vector = json.loads(row.emotion_vector or "{}")
        except json.JSONDecodeError:
            vector = {}
        return {
            "id": row.id,
            "character_id": row.character_id,
            "message_id": row.message_id,
            "trigger_role": row.trigger_role,
            "primary_emotion": row.primary_emotion,
            "secondary_emotion": row.secondary_emotion,
            "intensity": float(row.intensity or 0.0),
            "emotion_vector": vector,
            "user_tone": row.user_tone,
            "cause": row.cause,
            "notes": MoralMatrixRepository._parse_json_or_text(row.notes),
            "created_at": (
                row.created_at.isoformat()
                if hasattr(row.created_at, "isoformat")
                else None
            ),
        }

    @staticmethod
    def _serialize_snapshot(row: MoralStateSnapshot) -> Dict[str, Any]:
        try:
            recommendations = json.loads(row.recommendations or "[]")
        except json.JSONDecodeError:
            recommendations = []
        try:
            hard_directives = json.loads(row.hard_directives or "[]")
        except json.JSONDecodeError:
            hard_directives = []
        try:
            meta = json.loads(row.meta or "{}")
        except json.JSONDecodeError:
            meta = {}
        return {
            "id": row.id,
            "trust": float(row.trust or 0.0),
            "stability": float(row.stability or 0.0),
            "sociability": float(row.sociability or 0.0),
            "resentment": float(row.resentment or 0.0),
            "mood": row.mood,
            "recommendations": recommendations,
            "hard_directives": hard_directives,
            "meta": meta,
            "created_at": (
                row.created_at.isoformat()
                if hasattr(row.created_at, "isoformat")
                else None
            ),
        }

    @staticmethod
    def _parse_json_or_text(value: Any) -> Any:
        if not isinstance(value, str) or not value.strip():
            return value

        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    @staticmethod
    def _tokenize(value: str) -> set[str]:
        text = str(value or "").lower()
        return {
            token
            for token in re.findall(r"[\wа-яё]{3,}", text, flags=re.IGNORECASE)
            if token
        }

    @staticmethod
    def _serialize_daily_summary(row: DailyMoralSummary) -> Dict[str, Any]:
        try:
            vector = json.loads(row.emotion_vector or "{}")
        except json.JSONDecodeError:
            vector = {}
        return {
            "id": row.id,
            "date": row.date.isoformat() if hasattr(row.date, "isoformat") else None,
            "dominant_emotion": row.dominant_emotion,
            "average_intensity": float(row.average_intensity or 0.0),
            "emotion_vector": vector,
            "trust": float(row.trust or 0.0),
            "stability": float(row.stability or 0.0),
            "sociability": float(row.sociability or 0.0),
            "resentment": float(row.resentment or 0.0),
            "summary": row.summary,
            "created_at": (
                row.created_at.isoformat()
                if hasattr(row.created_at, "isoformat")
                else None
            ),
            "updated_at": (
                row.updated_at.isoformat()
                if hasattr(row.updated_at, "isoformat")
                else None
            ),
        }
