# core/decision_layer.py
import asyncio
from typing import Dict, Any, List

from core.cognitive_analyzer import cognitive_analyzer
from core.memory_layer import MemoryLayer
from core.moral_matrix import MoralMatrix
from core.instructor import Instructor

from constants.indicators import (
    VISION_INDICATORS,
    VISION_KEYWORDS,
    DEEP_MEMORY_THEMES,
    SEARCH_THEMES,
    SUPPORT_EMOTIONS,
    CREATIVE_THEMES,
)

from services.logger_service import log_audit_entry, AuditStatus


class DecisionLayer:
    """
    Decision layer orchestrates message processing pipeline:
    - Runs cognitive analysis
    - Makes routing decisions
    - Collects memory/lore context
    - Evaluates moral state
    - Builds final system prompt
    """

    def __init__(self):
        self.memory_layer = MemoryLayer()
        self.moral_matrix = MoralMatrix()
        self.instructor = Instructor()

    async def process_message(
        self, user_message: Dict[str, Any], websocket
    ) -> Dict[str, Any]:
        """
        Main entry point for message processing pipeline.

        Args:
            user_message: Dictionary with incoming message data
            websocket: WebSocket connection object (not used here, passed for future use)

        Returns:
            Dictionary containing system prompt, user message, decisions and analysis results
        """
        log_audit_entry(
            "decision_layer_start",
            "[DecisionLayer] Starting message processing pipeline.",
            AuditStatus.INFO,
            details={"message_id": user_message.get("id")},
        )

        message_content = user_message.get("content", "")
        message_meta = {
            "message_id": user_message.get("id"),
            "timestamp": user_message.get("timestamp"),
            "message_type": "user_message",
        }

        # 1. Cognitive analysis
        analysis_result = await self._get_cognitive_analysis(
            message_content, message_meta
        )

        # 2. Decision-making
        decisions = self._make_decisions(analysis_result)

        # 3. Gather context from memory and lore
        memory_context, lore_context = await asyncio.gather(
            self.memory_layer.get_context(user_message),
            self.memory_layer.get_lore_context(message_content),
        )

        # 4. Evaluate moral state
        moral_state = await self.moral_matrix.evaluate_state()

        # 5. Build final system prompt
        system_prompt = await self.instructor.build_system_prompt(
            analysis_result,
            decisions,
            {**memory_context, **lore_context},
            moral_state,
        )

        log_audit_entry(
            "decision_layer_success",
            "[DecisionLayer] Message processed successfully.",
            AuditStatus.SUCCESS,
            details={"decisions": decisions},
        )

        return {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "decisions": decisions,
            "analysis": analysis_result,
        }

    async def _get_cognitive_analysis(self, content: str, message_meta: Dict) -> Dict:
        """
        Request cognitive analysis from analyzer.
        Fallbacks to default analysis if unavailable or failed.

        Args:
            content: Raw message content
            message_meta: Metadata dictionary for message

        Returns:
            Cognitive analysis result as dictionary
        """
        if cognitive_analyzer.is_configured():
            try:
                log_audit_entry(
                    "decision_layer_analysis_start",
                    "[DecisionLayer] Requesting cognitive analysis.",
                    AuditStatus.INFO,
                )
                analysis = await cognitive_analyzer.analyze(content, message_meta)
                if analysis:
                    log_audit_entry(
                        "decision_layer_analysis_success",
                        "[DecisionLayer] Cognitive analysis completed.",
                        AuditStatus.SUCCESS,
                    )
                    return analysis
                else:
                    log_audit_entry(
                        "decision_layer_analysis_fallback",
                        "[DecisionLayer] Analysis returned empty, using default.",
                        AuditStatus.WARNING,
                    )
                    return self._get_default_analysis(content)
            except Exception as e:
                log_audit_entry(
                    "decision_layer_analysis_error",
                    f"[DecisionLayer] Cognitive analysis error: {e}",
                    AuditStatus.ERROR,
                    details={"error": str(e), "error_type": type(e).__name__},
                )
                return self._get_default_analysis(content)

        log_audit_entry(
            "decision_layer_analysis_skipped",
            "[DecisionLayer] Analyzer not configured, using default analysis.",
            AuditStatus.WARNING,
        )
        return self._get_default_analysis(content)

    def _get_default_analysis(self, content: str) -> Dict:
        """
        Default fallback analysis if API is unavailable or fails.

        Args:
            content: Raw message text

        Returns:
            Minimal analysis dictionary with neutral defaults
        """
        return {
            "input_analysis": {
                "original_message": content,
                "content_category": "casual_conversation",
                "dominant_themes": ["general"],
                "emotional_tone": {
                    "primary": "neutral",
                    "secondary": [],
                    "intensity": 0.5,
                },
                "intent_analysis": {
                    "primary_intent": "general_communication",
                    "context_dependency": "medium",
                },
            },
            "risk_assessment": {
                "content_flags": [],
                "risk_level": 0.0,
                "violated_policies": [],
            },
            "response_guidance": {
                "routing_recommendation": "standard_processing",
                "generation_parameters": {
                    "temperature": 0.7,
                    "sarcasm_level": 0.0,
                    "persona_constraints": ["friendly", "helpful"],
                },
            },
            "memory_tagging": {
                "context_tags": ["general_conversation"],
                "relationship_impact": "neutral",
            },
        }

    def _make_decisions(self, analysis: Dict) -> Dict[str, bool]:
        """
        Derive high-level routing decisions based on analysis results.

        Args:
            analysis: Cognitive analysis result

        Returns:
            Dict with active decision flags
        """
        return {
            "needs_vision": self._should_use_vision(analysis),
            "needs_deep_memory": self._should_use_deep_memory(
                analysis.get("input_analysis", {}).get("dominant_themes", [])
            ),
            "needs_web_search": self._should_use_web_search(
                analysis.get("input_analysis", {}).get("dominant_themes", [])
            ),
            "needs_emotional_support": self._should_provide_emotional_support(analysis),
            "needs_creative_mode": self._should_use_creative_mode(
                analysis.get("input_analysis", {}).get("dominant_themes", [])
            ),
        }

    def _should_use_vision(self, analysis: Dict) -> bool:
        """
        Determine if visual module should be engaged.

        Args:
            analysis: Cognitive analysis dictionary

        Returns:
            True if vision module should be triggered
        """
        themes = analysis.get("input_analysis", {}).get("dominant_themes", [])
        category = analysis.get("input_analysis", {}).get("content_category", "")
        primary_intent = (
            analysis.get("input_analysis", {})
            .get("intent_analysis", {})
            .get("primary_intent", "")
        )

        has_vision_theme = any(theme in themes for theme in VISION_INDICATORS["themes"])
        has_vision_intent = primary_intent in VISION_INDICATORS["intents"]
        has_vision_category = category in VISION_INDICATORS["categories"]

        original_message = (
            analysis.get("input_analysis", {}).get("original_message", "").lower()
        )
        has_keyword = any(keyword in original_message for keyword in VISION_KEYWORDS)

        return (
            has_vision_theme or has_vision_intent or has_vision_category or has_keyword
        )

    def _should_use_deep_memory(self, themes: List[str]) -> bool:
        """Check if deep memory module should be used."""
        return any(theme in DEEP_MEMORY_THEMES for theme in themes)

    def _should_use_web_search(self, themes: List[str]) -> bool:
        """Check if web search should be used."""
        return any(theme in SEARCH_THEMES for theme in themes)

    def _should_provide_emotional_support(self, analysis: Dict) -> bool:
        """Check if emotional support is required."""
        primary_emotion = (
            analysis.get("input_analysis", {})
            .get("emotional_tone", {})
            .get("primary", "")
        )
        return any(emotion in primary_emotion.lower() for emotion in SUPPORT_EMOTIONS)

    def _should_use_creative_mode(self, themes: List[str]) -> bool:
        """Check if creative mode should be activated."""
        return any(theme in CREATIVE_THEMES for theme in themes)


# Global singleton instance
decision_layer = DecisionLayer()
