"""Service surface of the factuality check.

Looks each extracted claim up in PAI's own memory:
  * lorebook (modules.memory.lorebook.search_entries) — primary source

Anchors lookup is intentionally NOT wired on this iteration: it requires
a character_id and the lorebook hits cover most factual snippets already.
We can extend later if false-negative rate is too high.

Contract: never raises. Lookup errors → skipped(lookup_error).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry

from .claim_extractor import extract_claims
from .types import FactualityResult


_DEFAULT_TOP_K = 3
_DEFAULT_MIN_SIM = 0.6
_DEFAULT_MAX_CLAIMS = 6
_DEFAULT_CLAIM_MIN_LEN = 3


def _read_settings() -> Dict[str, Any]:
    cfg = config_service.get_config_value("factuality", {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "gate_on_low_confidence": bool(cfg.get("gate_on_low_confidence", True)),
        "top_k": int(cfg.get("top_k", _DEFAULT_TOP_K) or _DEFAULT_TOP_K),
        "min_similarity": float(cfg.get("min_similarity", _DEFAULT_MIN_SIM) or _DEFAULT_MIN_SIM),
        "max_claims": int(cfg.get("max_claims", _DEFAULT_MAX_CLAIMS) or _DEFAULT_MAX_CLAIMS),
        "claim_min_length": int(cfg.get("claim_min_length", _DEFAULT_CLAIM_MIN_LEN) or _DEFAULT_CLAIM_MIN_LEN),
    }


def check_factuality(
    *,
    output: str,
    confidence_low: bool = False,
    extra_context: Optional[Dict[str, Any]] = None,
) -> FactualityResult:
    """Run a factuality gate against the assistant output.

    Default policy:
      * enabled=False → skipped(disabled)
      * empty output → skipped(empty_output)
      * gate_on_low_confidence=True and confidence_low=False → skipped(gated)
      * no extracted claims → skipped(no_claims)
      * lookup error → skipped(lookup_error)

    Never raises.
    """
    settings = _read_settings()
    if not settings["enabled"]:
        return FactualityResult(skipped=True, skip_reason="disabled")

    if not (output or "").strip():
        return FactualityResult(skipped=True, skip_reason="empty_output")

    if settings["gate_on_low_confidence"] and not confidence_low:
        return FactualityResult(skipped=True, skip_reason="gated")

    claims = extract_claims(
        output,
        max_claims=settings["max_claims"],
        min_length=settings["claim_min_length"],
    )
    if not claims:
        return FactualityResult(skipped=True, skip_reason="no_claims")

    try:
        from modules.memory import lorebook as lorebook_module
    except Exception as exc:
        log_audit_entry(
            "factuality_lorebook_import_failed",
            "[Factuality] Lorebook module unavailable.",
            AuditStatus.WARNING,
            details={"error": str(exc)},
        )
        return FactualityResult(
            skipped=True,
            skip_reason="lookup_import_error",
            error=str(exc),
            claims=claims,
        )

    sources_found = 0
    per_claim: List[Dict[str, Any]] = []
    for claim in claims:
        try:
            hits = lorebook_module.search_entries(
                claim,
                top_k=settings["top_k"],
                min_similarity=settings["min_similarity"],
            )
        except Exception as exc:
            per_claim.append({"claim": claim, "hits": 0, "error": str(exc)[:200]})
            continue
        count = len(hits or [])
        per_claim.append({"claim": claim, "hits": count})
        sources_found += count

    return FactualityResult(
        checked=True,
        claims=claims,
        sources_found=sources_found,
        supported=sources_found > 0,
        skipped=False,
        extra={"per_claim": per_claim},
    )
