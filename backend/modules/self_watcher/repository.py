"""SQLite-backed repository for expectation_events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from modules.database.core import engine


class SelfWatcherRepository:
    """Append-only writes and reads for the expectation_events table.

    Never raises out of the module — callers (service.check_expectation,
    nightly reflection) need a no-throw contract.
    """

    def insert(
        self,
        *,
        character_id: str,
        prev_assistant_message_id: Optional[str],
        triggering_user_message_id: Optional[str],
        pai_predicted_emotion: Optional[str],
        pai_predicted_valence: Optional[str],
        user_actual_tone: Optional[str],
        user_actual_valence: Optional[str],
        mismatch_score: float,
        notes: Optional[str] = None,
    ) -> Optional[str]:
        entry_id = str(uuid.uuid4())
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO expectation_events (
                            id, character_id,
                            prev_assistant_message_id, triggering_user_message_id,
                            pai_predicted_emotion, pai_predicted_valence,
                            user_actual_tone, user_actual_valence,
                            mismatch_score, notes, created_at
                        ) VALUES (
                            :id, :character_id,
                            :prev_msg, :trig_msg,
                            :pred_emo, :pred_val,
                            :act_tone, :act_val,
                            :score, :notes, :created_at
                        )
                        """
                    ),
                    {
                        "id": entry_id,
                        "character_id": character_id,
                        "prev_msg": prev_assistant_message_id,
                        "trig_msg": triggering_user_message_id,
                        "pred_emo": pai_predicted_emotion,
                        "pred_val": pai_predicted_valence,
                        "act_tone": user_actual_tone,
                        "act_val": user_actual_valence,
                        "score": float(mismatch_score or 0.0),
                        "notes": notes,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            return entry_id
        except Exception:
            return None

    def list_recent(
        self,
        *,
        character_id: str,
        lookback_days: int = 7,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        """
                        SELECT id, character_id,
                               prev_assistant_message_id, triggering_user_message_id,
                               pai_predicted_emotion, pai_predicted_valence,
                               user_actual_tone, user_actual_valence,
                               mismatch_score, notes, created_at
                        FROM expectation_events
                        WHERE character_id = :character_id
                          AND created_at >= datetime('now', :window)
                        ORDER BY created_at DESC
                        LIMIT :limit
                        """
                    ),
                    {
                        "character_id": character_id,
                        "window": f"-{int(lookback_days)} days",
                        "limit": int(limit),
                    },
                ).fetchall()
        except Exception:
            return []
        return [dict(row._mapping) for row in rows]


self_watcher_repository = SelfWatcherRepository()
