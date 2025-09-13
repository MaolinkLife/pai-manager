# core/decision_layer.py
import json
import asyncio
from typing import Dict, Any, List
from core.cognitive_analyzer import cognitive_analyzer
from core.memory_layer import MemoryLayer
from core.moral_matrix import MoralMatrix
from core.instructor import Instructor


class DecisionLayer:
    def __init__(self):
        self.memory_layer = MemoryLayer()
        self.moral_matrix = MoralMatrix()
        self.instructor = Instructor()

    async def process_message(
        self, user_message: Dict[str, Any], websocket
    ) -> Dict[str, Any]:
        """
        Основная точка входа для обработки сообщения
        """
        message_content = user_message.get("content", "")
        message_meta = {
            "message_id": user_message.get("id"),
            "timestamp": user_message.get("timestamp"),
            "message_type": "user_message",
        }

        # 1. Получаем когнитивный анализ
        analysis_result = await self._get_cognitive_analysis(
            message_content, message_meta
        )

        # 2. Принимаем решения на основе анализа
        decisions = self._make_decisions(analysis_result)

        # 3. Собираем контекст из памяти
        memory_context = await self.memory_layer.get_context(user_message)

        # 4. Оцениваем моральное состояние
        moral_state = await self.moral_matrix.evaluate_state()

        # 5. Формируем системный промпт через Instructor
        system_prompt = await self.instructor.build_system_prompt(
            analysis_result, decisions, memory_context, moral_state
        )

        return {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "decisions": decisions,
            "analysis": analysis_result,
        }

    async def _get_cognitive_analysis(self, content: str, message_meta: Dict) -> Dict:
        """Получаем когнитивный анализ"""
        if cognitive_analyzer.is_configured():
            try:
                # Ждем результата анализа
                analysis = await cognitive_analyzer.analyze(content, message_meta)
                return analysis or self._get_default_analysis(content)
            except Exception as e:
                print(f"[DecisionLayer] Ошибка анализа: {e}")
                return self._get_default_analysis(content)
        return self._get_default_analysis(content)

    def _get_default_analysis(self, content: str) -> Dict:
        """Дефолтный анализ"""
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
        """Принимаем решения на основе анализа"""
        themes = analysis.get("input_analysis", {}).get("dominant_themes", [])
        content_category = analysis.get("input_analysis", {}).get(
            "content_category", ""
        )

        return {
            "needs_vision": self._should_use_vision(analysis),  # Передаем весь анализ
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
        """Определяем, нужно ли подключать визуальный модуль на основе полного анализа"""

        # Получаем темы из анализа
        themes = analysis.get("input_analysis", {}).get("dominant_themes", [])
        content_category = analysis.get("input_analysis", {}).get(
            "content_category", ""
        )
        primary_intent = (
            analysis.get("input_analysis", {})
            .get("intent_analysis", {})
            .get("primary_intent", "")
        )

        # Список тем и интентов, указывающих на запрос визуального контента
        vision_indicators = {
            "themes": [
                "screen_sharing",
                "visual_access",
                "screen_capture",
                "visual_confirmation",
                "screen_viewing",
                "screenshot_analysis",
            ],
            "intents": [
                "request_visual_confirmation",
                "request_screen_capture",
                "ask_for_visual_feedback",
            ],
            "categories": ["technical_question", "visual_request"],
        }

        # Проверяем наличие индикаторов
        has_vision_theme = any(theme in themes for theme in vision_indicators["themes"])
        has_vision_intent = primary_intent in vision_indicators["intents"]
        has_vision_category = content_category in vision_indicators["categories"]

        # Также проверяем ключевые слова для дополнительной надежности
        original_message = (
            analysis.get("input_analysis", {}).get("original_message", "").lower()
        )
        vision_keywords = [
            "видишь",
            "покажи",
            "скрин",
            "экран",
            "screen",
            "view",
            "see",
        ]
        has_keyword = any(keyword in original_message for keyword in vision_keywords)

        return (
            has_vision_theme or has_vision_intent or has_vision_category or has_keyword
        )

    def _should_use_deep_memory(self, themes: List[str]) -> bool:
        deep_memory_themes = [
            "personal_history",
            "past_events",
            "memories",
            "воспоминания",
            "прошлое",
        ]
        return any(theme in deep_memory_themes for theme in themes)

    def _should_use_web_search(self, themes: List[str]) -> bool:
        search_themes = [
            "current_events",
            "news",
            "facts",
            "actual_information",
            "новости",
            "факты",
        ]
        return any(theme in search_themes for theme in themes)

    def _should_provide_emotional_support(self, analysis: Dict) -> bool:
        emotional_tone = analysis.get("input_analysis", {}).get("emotional_tone", {})
        primary_emotion = emotional_tone.get("primary", "")
        support_emotions = [
            "sad",
            "upset",
            "frustrated",
            "lonely",
            "грустный",
            "расстроенный",
        ]
        return any(emotion in primary_emotion.lower() for emotion in support_emotions)

    def _should_use_creative_mode(self, themes: List[str]) -> bool:
        creative_themes = [
            "creative",
            "storytelling",
            "imagination",
            "fantasy",
            "творчество",
            "история",
        ]
        return any(theme in creative_themes for theme in themes)


# Глобальный экземпляр
decision_layer = DecisionLayer()
