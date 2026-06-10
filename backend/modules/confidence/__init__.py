"""Confidence estimation (0.9.0 Wave 2, §3.8).

Post-generation mini LLM call that scores how confident PAI should be that
the output addressed the user message. The score is stored on
``History.runtime_meta.confidence`` for downstream consumers (Factuality
check §3.9, UI low-confidence hint in Phase 10).

Contract: never raises. Low confidence is a SIGNAL, not an anomaly — it
flows into audit logs as WARNING but does NOT land in DebugVault (DebugVault
is for curated anomalies).
"""

from .service import estimate_confidence, get_confidence_threshold
from .types import ConfidenceResult

__all__ = [
    "estimate_confidence",
    "get_confidence_threshold",
    "ConfidenceResult",
]
