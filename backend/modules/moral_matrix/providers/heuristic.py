"""Heuristic moral provider used as default fallback."""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import MoralMatrixProvider


class HeuristicMoralProvider(MoralMatrixProvider):
    """Generates a lightweight narrative without calling external services."""

    name = "heuristic"

    async def run(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # No model answered: her state stays the one she came in with. The tone of
        # the human is his, and without a verdict nothing about her has changed.
        current_state = payload.get("currentState") or {}
        metrics = current_state.get("metrics") or payload.get("metrics") or {}
        emotion = current_state.get("emotion") or payload.get("current_emotion") or "neutral"
        intensity = float(current_state.get("intensity") or payload.get("emotion_intensity") or 0.0)

        trust = metrics.get("trust", 0.5)
        resentment = metrics.get("resentment", 0.0)

        tone_parts = [f"emotion: {emotion} ({intensity:.2f})"]
        tone_parts.append(f"trust={trust:.2f}")
        tone_parts.append(f"resentment={resentment:.2f}")

        narrative = " | ".join(tone_parts)
        affective_state = dict(payload.get("affective_state") or payload.get("current_state") or {})

        hard_directives: list[str] = []
        if resentment > 0.7:
            hard_directives.append("system:delay_response")
        if trust < 0.2:
            hard_directives.append("system:withhold_private_topics")

        return {
            "summary": narrative,
            "current_state": affective_state,
            "emotion_vector_delta": {},
            "metrics_delta": {},
            "hard_directives": hard_directives,
            "soft_recommendations": [],
        }
