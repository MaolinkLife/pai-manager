"""Self-Watcher / Meta-cognition (0.9.0 Wave 2, §3.7).

Records mismatches between what PAI predicted the user would feel
(moral_matrix.current_emotion on the previous turn) and the user's
actual reaction (analyzer.emotional_tone on the next turn). Aggregates
into nightly self-reflection prose via LLM.

Contract:
  * Never raises. Self-Watcher is observation-only — it must not break
    the generation pipeline.
  * Does NOT change PAI's behaviour on the current turn. Its insight
    flows into the daily diary, not into hot-path decisions.
"""

from .classifier import classify_valence, score_mismatch
from .repository import SelfWatcherRepository, self_watcher_repository
from .service import check_expectation, record_nightly_reflection
from .types import ExpectationCheckResult, ExpectationEventDTO

__all__ = [
    "classify_valence",
    "score_mismatch",
    "SelfWatcherRepository",
    "self_watcher_repository",
    "check_expectation",
    "record_nightly_reflection",
    "ExpectationCheckResult",
    "ExpectationEventDTO",
]
