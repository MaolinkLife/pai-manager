"""Validator dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ValidationError(Exception):
    """Raised when the validator itself fails (LLM unreachable, malformed JSON
    after retries, etc.). Not raised for low compliance — that's a normal
    result, surfaced via ``ValidationResult.compliance``."""


@dataclass
class ValidationResult:
    """Outcome of a single validation pass.

    ``compliance`` ∈ [0.0, 1.0] — how well the output followed the instructions.
    ``violations`` lists short strings naming each specific rule the model
    broke (empty when compliance is high, but the model may also return some
    even at high scores to flag minor issues).

    ``skipped`` is true when the validator was disabled or had no provider —
    callers treat skipped as "no opinion", not as "passed".

    ``raw`` keeps the LLM payload for debugging — never expose to the user.
    """
    compliance: float = 1.0
    violations: List[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def is_acceptable(self, threshold: float) -> bool:
        if self.skipped:
            return True  # don't block when validator opted out
        return self.compliance >= threshold

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compliance": round(float(self.compliance), 4),
            "violations": list(self.violations),
            "skipped": bool(self.skipped),
            "skip_reason": self.skip_reason,
            "error": self.error,
        }
