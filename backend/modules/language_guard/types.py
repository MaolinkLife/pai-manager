"""Result types for the language guard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(slots=True)
class LanguageCheckResult:
    """Outcome of a language compliance check.

    ok=True means we are confident the output matches the expected language.
    skipped=True means the check could not run (disabled, too short, broken
    detector). A skipped result is NEVER treated as a failure — same contract
    as the Validator.
    """

    expected: str = ""
    detected: str = ""
    dominance: float = 0.0
    ok: bool = True
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "expected": self.expected,
            "detected": self.detected,
            "dominance": round(float(self.dominance), 4),
            "ok": bool(self.ok),
            "skipped": bool(self.skipped),
        }
        if self.skip_reason:
            payload["skip_reason"] = self.skip_reason
        if self.error:
            payload["error"] = self.error
        if self.extra:
            payload["extra"] = self.extra
        return payload
