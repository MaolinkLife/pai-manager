"""Result type for confidence estimation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(slots=True)
class ConfidenceResult:
    """Outcome of a confidence estimation pass.

    skipped=True means the check did not run (disabled, empty input, parse
    error). Same contract as Validator and LanguageGuard: skipped is NEVER
    a failure. Callers only act on `is_low(threshold)` when not skipped.
    """

    score: float = 0.0
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""
    raw: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def is_low(self, threshold: float) -> bool:
        if self.skipped:
            return False
        return self.score < threshold

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "score": round(float(self.score), 4),
            "skipped": bool(self.skipped),
        }
        if self.skip_reason:
            payload["skip_reason"] = self.skip_reason
        if self.error:
            payload["error"] = self.error
        if self.raw:
            payload["raw"] = self.raw[:400]
        if self.extra:
            payload["extra"] = self.extra
        return payload
