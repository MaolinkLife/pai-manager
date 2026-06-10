"""Result and DTO types for Self-Watcher."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(slots=True)
class ExpectationCheckResult:
    """Outcome of a single predicted-vs-actual comparison.

    recorded=True means a row was inserted into expectation_events.
    skipped=True means the comparison did not produce anything to record —
    disabled, missing previous prediction, below threshold, etc. NEVER
    a failure on its own.
    """

    recorded: bool = False
    event_id: Optional[str] = None
    mismatch_score: float = 0.0
    pai_predicted_emotion: str = ""
    pai_predicted_valence: str = ""
    user_actual_tone: str = ""
    user_actual_valence: str = ""
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "recorded": bool(self.recorded),
            "mismatch_score": round(float(self.mismatch_score), 4),
            "pai_predicted_emotion": self.pai_predicted_emotion,
            "pai_predicted_valence": self.pai_predicted_valence,
            "user_actual_tone": self.user_actual_tone,
            "user_actual_valence": self.user_actual_valence,
            "skipped": bool(self.skipped),
        }
        if self.event_id:
            payload["event_id"] = self.event_id
        if self.skip_reason:
            payload["skip_reason"] = self.skip_reason
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass(slots=True)
class ExpectationEventDTO:
    """DB row as a plain dict-like dataclass for downstream consumers."""

    id: str
    character_id: str
    prev_assistant_message_id: Optional[str]
    triggering_user_message_id: Optional[str]
    pai_predicted_emotion: Optional[str]
    pai_predicted_valence: Optional[str]
    user_actual_tone: Optional[str]
    user_actual_valence: Optional[str]
    mismatch_score: float
    notes: Optional[str]
    created_at: str
