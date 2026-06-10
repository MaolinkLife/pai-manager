"""Factuality check (0.9.0 Wave 2, §3.9).

Post-generation hallucination signal: extracts factual claims from the
output via regex, looks them up against PAI's OWN memory (lorebook), and
records whether the claims are supported.

Contract:
  * Never raises. Broken extractor / failing lookup → skipped result.
  * NEVER fetches anything external (no web search). Web-based knowledge
    acquisition belongs to §3.10 Skill Training which is OUT OF CORE.
  * Does NOT rewrite the assistant output. Marks runtime_meta only;
    the UI decides whether to render an "[unverified]" hint (Phase 10).
  * Low confidence (§3.8) acts as the natural gate — by default the
    factuality check only runs when confidence is already flagged low.
"""

from .claim_extractor import extract_claims
from .service import check_factuality
from .types import FactualityResult

__all__ = [
    "extract_claims",
    "check_factuality",
    "FactualityResult",
]
