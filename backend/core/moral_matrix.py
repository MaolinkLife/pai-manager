# core/moral_matrix.py
from typing import Dict, Any
import asyncio


class MoralMatrix:
    def __init__(self):
        self.emotional_state = {
            "joy": 0.5,
            "sadness": 0.2,
            "anger": 0.1,
            "fear": 0.1,
            "surprise": 0.3,
            "disgust": 0.05,
        }
        self.relationship_score = 0.7  # 0-1 scale

    async def evaluate_state(self) -> Dict[str, Any]:
        """
        Оцениваем текущее моральное/эмоциональное состояние
        """
        # TODO: реализовать более сложную логику оценки
        dominant_emotion = max(self.emotional_state.items(), key=lambda x: x[1])

        return {
            "current_emotion": self._emotion_to_text(dominant_emotion[0]),
            "emotion_intensity": dominant_emotion[1],
            "relationship_status": self._relationship_status(),
            "recommendations": self._get_behavioral_recommendations(
                dominant_emotion[0]
            ),
        }

    def _emotion_to_text(self, emotion: str) -> str:
        """Преобразуем эмоцию в текст"""
        emotion_map = {
            "joy": "радость",
            "sadness": "грусть",
            "anger": "раздражение",
            "fear": "тревога",
            "surprise": "удивление",
            "disgust": "раздражение",
        }
        return emotion_map.get(emotion, emotion)

    def _relationship_status(self) -> str:
        """Определяем статус отношений"""
        if self.relationship_score > 0.8:
            return "очень близкие"
        elif self.relationship_score > 0.6:
            return "дружеские"
        elif self.relationship_score > 0.4:
            return "нейтральные"
        else:
            return "формальные"

    def _get_behavioral_recommendations(self, dominant_emotion: str) -> list[str]:
        """Получаем рекомендации по поведению"""
        recommendations = {
            "joy": ["будь игривой", "поддерживай позитивный тон"],
            "sadness": ["окажи поддержку", "будь сочувственной"],
            "anger": ["будь терпеливой", "избегай конфронтации"],
            "fear": ["будь успокаивающей", "дай уверенности"],
            "surprise": ["будь любопытной", "поддерживай интерес"],
            "disgust": ["будь деликатной", "избегай споров"],
        }
        return recommendations.get(dominant_emotion, ["будь естественной"])
