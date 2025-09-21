# core/instructor.py
from typing import Dict, Any

from services.api_service import (
    load_system_prompt,
    add_vision_context_to_system_prompt,
)
from services.logger_service import log_audit_entry, AuditStatus
from constants.rules import SYSTEM_RULES
from constants.messages import (
    DEFAULT_CONTEXT,
    NO_MEMORY,
    NO_KNOWLEDGE,
    DEFAULT_PERSONA_STYLE,
)


class Instructor:
    """
    Instructor assembles the final structured system prompt
    based on analysis, decisions, memory and moral state.
    """

    async def build_system_prompt(
        self,
        analysis: Dict[str, Any],
        decisions: Dict[str, bool],
        memory_context: Dict[str, Any],
        moral_state: Dict[str, Any],
    ) -> str:
        """
        Build structured system prompt combining:
        - Base persona prompt
        - Dialogue context
        - Memory and lore knowledge
        - Style/persona constraints
        - Current emotional state
        - Hard system rules
        - Active decisions

        Args:
            analysis: Cognitive analysis result
            decisions: Dictionary of active decision flags
            memory_context: Memory and lore context
            moral_state: Current moral/emotional state

        Returns:
            Final system prompt string
        """
        try:
            log_audit_entry(
                "instructor_prompt_build_start",
                "[Instructor] Building system prompt.",
                AuditStatus.INFO,
            )

            base_prompt = load_system_prompt()
            sections = []

            # [CORE] - base persona
            sections.append(f"[CORE]\n{base_prompt}")

            # [CONTEXT] - summary of current dialogue
            context_parts = []
            themes = analysis.get("input_analysis", {}).get("dominant_themes", [])
            if themes:
                context_parts.append(f"Themes: {', '.join(themes)}")

            intent = (
                analysis.get("input_analysis", {})
                .get("intent_analysis", {})
                .get("primary_intent", "")
            )
            if intent:
                context_parts.append(f"Intent: {intent}")

            emotional_tone = (
                analysis.get("input_analysis", {})
                .get("emotional_tone", {})
                .get("primary", "")
            )
            if emotional_tone:
                context_parts.append(f"Emotional tone: {emotional_tone}")

            sections.append(
                f"[CONTEXT]\n{'; '.join(context_parts)}"
                if context_parts
                else f"[CONTEXT]\n{DEFAULT_CONTEXT}"
            )

            # [MEMORY] - important facts
            key_facts = memory_context.get("key_facts")
            if key_facts:
                joined_facts = "; ".join(key_facts)
                sections.append(f"[MEMORY]\n{joined_facts}")
            else:
                sections.append(f"[MEMORY]\n{NO_MEMORY}")

            # [KNOWLEDGE] - relevant lore knowledge
            if memory_context.get("lore_matches"):
                joined_knowledge = "\n---\n".join(memory_context["lore_matches"])
                sections.append(f"[KNOWLEDGE]\n{joined_knowledge}")
            else:
                sections.append(f"[KNOWLEDGE]\n{NO_KNOWLEDGE}")

            # [INSTRUCTION] - persona style
            persona_constraints = (
                analysis.get("response_guidance", {})
                .get("generation_parameters", {})
                .get("persona_constraints", [])
            )
            # TODO: Temporarily disabled to avoid overwriting the PAI persona
            # if persona_constraints:
            #     sections.append(
            #         f"[INSTRUCTION]\nPersona style: {', '.join(persona_constraints)}"
            #     )
            # else:
            #     sections.append(f"[INSTRUCTION]\n{DEFAULT_PERSONA_STYLE}")

            # [EMOTION] - current mood
            current_emotion = moral_state.get("current_emotion", "neutral")
            sections.append(f"[EMOTION]\nCurrent emotional state: {current_emotion}")

            # [RULES] - strict constraints
            sections.append(f"[RULES]\n" + "\n".join(SYSTEM_RULES))

            # [DECISIONS] - active modes
            active_decisions = [k for k, v in decisions.items() if v]
            if active_decisions:
                sections.append(
                    f"[DECISIONS]\nActive modes: {', '.join(active_decisions)}"
                )

            final_prompt = "\n\n".join(sections)

            user_text = (
                analysis.get("input_analysis", {})
                .get("original_message", "")
                or ""
            )
            final_prompt = add_vision_context_to_system_prompt(
                final_prompt, user_text
            )

            log_audit_entry(
                "instructor_prompt_build_success",
                "[Instructor] System prompt successfully built.",
                AuditStatus.SUCCESS,
                details={"sections_count": len(sections)},
            )

            return final_prompt

        except Exception as e:
            log_audit_entry(
                "instructor_prompt_build_error",
                f"[Instructor] Error while building system prompt: {e}",
                AuditStatus.ERROR,
                details={"error": str(e), "error_type": type(e).__name__},
            )
            # fallback — minimal prompt
            return "[CORE]\nSystem prompt unavailable due to error."

    async def format_for_api(
        self, system_prompt: str, user_message: Dict[str, Any]
    ) -> list:
        """
        Format message history for API consumption.

        Args:
            system_prompt: Final system prompt string
            user_message: Incoming user message dictionary

        Returns:
            List of messages in OpenAI-compatible format
        """
        log_audit_entry(
            "instructor_format_for_api",
            "[Instructor] Formatting message history for API.",
            AuditStatus.INFO,
            details={"message_id": user_message.get("id")},
        )

        return [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_message.get("content", ""),
                "id": user_message.get("id"),
            },
        ]
