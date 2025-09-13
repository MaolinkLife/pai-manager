# core/instructor.py
from typing import Dict, Any
import json


class Instructor:
    async def build_system_prompt(
        self,
        analysis: Dict[str, Any],
        decisions: Dict[str, bool],
        memory_context: Dict[str, Any],
        moral_state: Dict[str, Any],
    ) -> str:
        """
        Собираем структурированный системный промпт
        """
        # Используем оригинальный промпт из файла
        from services.api_service import load_system_prompt

        base_prompt = load_system_prompt()

        # Собираем секции
        sections = []

        # [CORE] - базовый промпт
        sections.append(f"[CORE]\n{base_prompt}")

        # [MEMORY] - контекст из памяти
        if memory_context.get("recent_conversation"):
            sections.append(f"[MEMORY]\n{memory_context['recent_conversation']}")
        else:
            sections.append("[MEMORY]\nВы только начали диалог.")

        # [CONTEXT] - темы и намерения из анализа
        context_parts = []
        themes = analysis.get("input_analysis", {}).get("dominant_themes", [])
        if themes:
            context_parts.append(f"Темы разговора: {', '.join(themes)}")

        intent = (
            analysis.get("input_analysis", {})
            .get("intent_analysis", {})
            .get("primary_intent", "")
        )
        if intent:
            context_parts.append(f"Намерение пользователя: {intent}")

        emotional_tone = (
            analysis.get("input_analysis", {})
            .get("emotional_tone", {})
            .get("primary", "")
        )
        if emotional_tone:
            context_parts.append(f"Эмоциональный тон: {emotional_tone}")

        if context_parts:
            sections.append(f"[CONTEXT]\n{'; '.join(context_parts)}")
        else:
            sections.append("[CONTEXT]\nОбычный диалог")

        # [INSTRUCTION] - рекомендации по стилю
        persona_constraints = (
            analysis.get("response_guidance", {})
            .get("generation_parameters", {})
            .get("persona_constraints", [])
        )
        if persona_constraints:
            sections.append(
                f"[INSTRUCTION]\nСтиль общения: {', '.join(persona_constraints)}"
            )
        else:
            sections.append("[INSTRUCTION]\nБудь естественной и дружелюбной")

        # [EMOTION] - текущее эмоциональное состояние
        current_emotion = moral_state.get("current_emotion", "нейтральное")
        sections.append(
            f"[EMOTION]\nТвое текущее эмоциональное состояние: {current_emotion}"
        )

        # [DECISIONS] - активные режимы
        active_decisions = [k for k, v in decisions.items() if v]
        if active_decisions:
            sections.append(
                f"[DECISIONS]\nАктивные режимы: {', '.join(active_decisions)}"
            )

        # Собираем финальный промпт
        final_prompt = "\n\n".join(sections)

        return final_prompt

    async def format_for_api(
        self, system_prompt: str, user_message: Dict[str, Any]
    ) -> list:
        """
        Форматируем историю для API Service
        """
        history = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": user_message.get("content", ""),
                "id": user_message.get("id"),
            },
        ]
        return history
