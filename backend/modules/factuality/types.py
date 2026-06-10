"""Result types for factuality check."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class FactualityResult:
    """Outcome of a factuality check pass.

    supported=True means at least one claim found corroborating evidence
    in PAI's own memory (lorebook / anchors). supported=False with
    claims>0 is the [unverified] signal.

    skipped=True means the check did not run — disabled, no claims found,
    gated by confidence, or lookup error. NEVER a failure on its own.
    """

    checked: bool = False
    claims: List[str] = field(default_factory=list)
    sources_found: int = 0
    supported: bool = True
    skipped: bool = False
    skip_reason: str = ""
    error: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "checked": bool(self.checked),
            "claims": list(self.claims),
            "sources_found": int(self.sources_found),
            "supported": bool(self.supported),
            "skipped": bool(self.skipped),
        }
        if self.skip_reason:
            payload["skip_reason"] = self.skip_reason
        if self.error:
            payload["error"] = self.error
        if self.extra:
            payload["extra"] = self.extra
        return payload
