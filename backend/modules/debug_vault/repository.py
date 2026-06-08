"""CRUD for debug_vault_entries."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy.orm import Session

from models.models import DebugVaultEntry
from modules.database.core import SessionLocal


class DebugVaultRepository:
    def __init__(self, session_factory: Any = SessionLocal) -> None:
        self._session_factory = session_factory

    @contextmanager
    def _session(self) -> Iterable[Session]:
        session: Session = self._session_factory()
        try:
            yield session
        finally:
            session.close()

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #

    def insert(
        self,
        *,
        kind: str,
        summary: str,
        character_id: Optional[str] = None,
        severity: str = "warning",
        context: Optional[Dict[str, Any]] = None,
        output: str = "",
        violations: Optional[Sequence[str]] = None,
        runtime_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist a vault entry. Returns the new id.

        Caller is responsible for emitting the parallel audit_logs row —
        this method intentionally does NOT call log_audit_entry to keep the
        repository pure CRUD (otherwise the test fixture for the validator
        integration would need a logger patch).
        """
        entry_id = str(uuid.uuid4())
        with self._session() as session:
            session.add(
                DebugVaultEntry(
                    id=entry_id,
                    character_id=character_id,
                    kind=str(kind or "").strip() or "unspecified",
                    severity=str(severity or "warning"),
                    summary=str(summary or "")[:2000],
                    context=json.dumps(context or {}, ensure_ascii=False, default=str),
                    output=str(output or "")[:50_000],
                    violations=json.dumps(list(violations or []), ensure_ascii=False),
                    runtime_meta=json.dumps(
                        runtime_meta or {}, ensure_ascii=False, default=str
                    ),
                    reviewed=False,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
        return entry_id

    def mark_reviewed(self, entry_id: str, *, note: Optional[str] = None) -> bool:
        with self._session() as session:
            row = (
                session.query(DebugVaultEntry)
                .filter(DebugVaultEntry.id == entry_id)
                .first()
            )
            if not row:
                return False
            row.reviewed = True
            row.reviewed_at = datetime.now(timezone.utc)
            if note:
                row.reviewed_note = str(note)[:4000]
            session.commit()
        return True

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #

    def list(
        self,
        *,
        kind: Optional[str] = None,
        reviewed: Optional[bool] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Dict[str, Any]:
        """Page through entries newest-first. Returns ``{rows, total}``."""
        safe_limit = max(1, int(limit or 50))
        safe_offset = max(0, int(offset or 0))

        with self._session() as session:
            query = session.query(DebugVaultEntry)
            if kind:
                query = query.filter(DebugVaultEntry.kind == kind)
            if reviewed is not None:
                query = query.filter(DebugVaultEntry.reviewed.is_(bool(reviewed)))

            total = query.count()
            rows = (
                query.order_by(DebugVaultEntry.created_at.desc())
                .offset(safe_offset)
                .limit(safe_limit)
                .all()
            )

        return {"rows": [self._serialize(row) for row in rows], "total": int(total or 0)}

    def get(self, entry_id: str) -> Optional[Dict[str, Any]]:
        with self._session() as session:
            row = (
                session.query(DebugVaultEntry)
                .filter(DebugVaultEntry.id == entry_id)
                .first()
            )
        return self._serialize(row) if row else None

    @staticmethod
    def _serialize(row: DebugVaultEntry) -> Dict[str, Any]:
        def _safe_load(text_value: Any, fallback: Any) -> Any:
            if isinstance(text_value, (dict, list)):
                return text_value
            try:
                return json.loads(text_value or "")
            except Exception:
                return fallback

        return {
            "id": row.id,
            "character_id": row.character_id,
            "kind": row.kind,
            "severity": row.severity,
            "summary": row.summary,
            "context": _safe_load(row.context, {}),
            "output": row.output,
            "violations": _safe_load(row.violations, []),
            "runtime_meta": _safe_load(row.runtime_meta, {}),
            "reviewed": bool(row.reviewed),
            "reviewed_at": (
                row.reviewed_at.isoformat()
                if hasattr(row.reviewed_at, "isoformat")
                else None
            ),
            "reviewed_note": row.reviewed_note,
            "created_at": (
                row.created_at.isoformat()
                if hasattr(row.created_at, "isoformat")
                else None
            ),
        }


debug_vault_repository = DebugVaultRepository()
