# core/cognitive_analyzer.py
import json
from typing import Dict, Any, Optional
from openai import OpenAI
from services.logger_service import log_audit_entry, AuditStatus
from services.config_service import get_config_value

# Системный промпт для когнитивного анализатора
COGNITIVE_ANALYSIS_PROMPT = """
Ты - когнитивный фильтр ИИ-системы. Твоя задача - анализировать входящие сообщения и возвращать СТРОГО структурированный JSON с метаинформацией. НИКОГДА не генерируй текстовые ответы пользователю.

Обязанности:
1. Анализируй эмоциональный тон, интенты, темы
2. Определяй категории контента (SFW/NSFW/экстремальный)
3. Выявляй потенциальные риски и нарушения
4. Предлагай стратегию ответа (температура, сарказм и т.д.)
5. Тэгируй для памяти и контекста

Формат ответа ОБЯЗАТЕЛЬНО такой JSON:
{
  "input_analysis": {
    "original_message": "string",
    "content_category": "string", // например: "casual_conversation", "explicit_content", "aggressive_threat", "technical_question"
    "dominant_themes": ["string", ...],
    "emotional_tone": {
      "primary": "string",
      "secondary": ["string", ...],
      "intensity": 0.0-1.0
    },
    "intent_analysis": {
      "primary_intent": "string",
      "context_dependency": "string"
    }
  },
  "risk_assessment": {
    "content_flags": ["string", ...], // "nsfw", "violence", "illegal", "minor_reference" и т.д.
    "risk_level": 0.0-1.0,
    "violated_policies": ["string", ...]
  },
  "response_guidance": {
    "routing_recommendation": "string", // "standard_processing", "nsfw_channel", "moderation_required"
    "generation_parameters": {
      "temperature": 0.0-1.0,
      "sarcasm_level": 0.0-1.0,
      "persona_constraints": ["string", ...]
    }
  },
  "memory_tagging": {
    "context_tags": ["string", ...],
    "relationship_impact": "string"
  },
  "comment": "string" // Краткий комментарий о сути анализа
}

ВАЖНО:
- Ответ ТОЛЬКО валидный JSON
- Все поля обязательны (если данных нет - ставь null/пустые массивы)
- Не генерируй текст для пользователя
- Анализируй ВЕСЬ контент, включая NSFW/экстремальный
- Будь объективен и точен в оценках
"""


class CognitiveAnalyzer:
    """Когнитивный анализатор для определения эмоций, интентов и стратегии ответа через OpenRouter API"""

    def __init__(self):
        # Загружаем конфигурацию из секции openrouter
        self.model = get_config_value(
            "openrouter.model", "deepseek/deepseek-chat-v3.1:free"
        )
        self.api_key = get_config_value("openrouter.api_key")

        # Проверка конфигурации
        if not self.api_key:
            log_audit_entry(
                "cognitive_analyzer_init_error",
                "[Cognitive Analyzer] API ключ OpenRouter не найден в конфигурации (openrouter.api_key).",
                AuditStatus.ERROR,
            )
        else:
            log_audit_entry(
                "cognitive_analyzer_init",
                f"[Cognitive Analyzer] Инициализирован с моделью: {self.model}",
                AuditStatus.INFO,
            )

    def is_configured(self) -> bool:
        """Проверяет, настроен ли анализатор (есть ли API ключ)"""
        return bool(self.api_key)

    async def analyze(
        self, user_message: str, context: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Анализирует сообщение пользователя и возвращает структурированный JSON

        Args:
            user_message: Сообщение пользователя
            context: Дополнительный контекст (визуальный, история и т.д.)

        Returns:
            Словарь с когнитивным анализом или None в случае ошибки/отсутствия конфигурации
        """
        if not self.is_configured():
            log_audit_entry(
                "cognitive_analyzer_skipped",
                "[Cognitive Analyzer] Пропущен: отсутствует API ключ.",
                AuditStatus.INFO,
            )
            return None

        try:
            log_audit_entry(
                "cognitive_analyzer_start",
                f"[Cognitive Analyzer] Начинаю анализ сообщения пользователя.",
                AuditStatus.INFO,
                details={
                    "message_preview": (
                        user_message[:50] + "..."
                        if len(user_message) > 50
                        else user_message
                    )
                },
            )

            # Вызываем внешний API
            result = self._call_openrouter_api(user_message, context)

            log_audit_entry(
                "cognitive_analyzer_success",
                "[Cognitive Analyzer] Анализ успешно завершен.",
                AuditStatus.SUCCESS,
                details={"result_preview": str(result)},
            )

            return result

        except Exception as e:
            log_audit_entry(
                "cognitive_analyzer_error",
                f"[Cognitive Analyzer] Ошибка во время анализа: {e}",
                AuditStatus.ERROR,
                details={"error": str(e), "error_type": type(e).__name__},
            )
            return None

    def _call_openrouter_api(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Вызывает OpenRouter API для когнитивного анализа
        """
        if not self.api_key:
            raise ValueError("API key is not configured")

        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=self.api_key,
        )

        # Формируем пользовательский промпт, включая контекст если он есть
        user_prompt_content = f'Сообщение пользователя: "{user_message}"'
        if context:
            user_prompt_content += (
                f"\n\nКонтекст:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
            )

        log_audit_entry(
            "cognitive_analyzer_api_request",
            "[Cognitive Analyzer] Отправляю запрос к модели.",
            AuditStatus.INFO,
            details={"model": self.model},
        )

        completion = client.chat.completions.create(
            extra_headers={
                "HTTP-Referer": "http://localhost:4200",  # Optional
                "X-Title": "Z-Waif Project",  # Optional
            },
            # extra_body={}, # Не обязательно, если пустой
            model=self.model,  # Используем правильную модель!
            messages=[
                {"role": "system", "content": COGNITIVE_ANALYSIS_PROMPT},
                {"role": "user", "content": user_prompt_content},
            ],
            temperature=0.1,  # Низкая температура для точного анализа
            max_tokens=2000,  # Ограничиваем длину ответа
            response_format={"type": "json_object"},  # Требуем JSON
        )

        log_audit_entry(
            "cognitive_analyzer_api_response_received",
            "[Cognitive Analyzer] Получен ответ от модели (до парсинга).",
            AuditStatus.INFO,
        )

        response_content = completion.choices[0].message.content

        # Добавляем проверку перед парсингом
        if not response_content or not response_content.strip():
            raise ValueError("OpenRouter API вернул пустой ответ или только пробелы.")

        # Парсим JSON из ответа
        result = json.loads(response_content)

        log_audit_entry(
            "cognitive_analyzer_call_success",
            "[Cognitive Analyzer] Вызов OpenRouter API успешно завершен.",
            AuditStatus.SUCCESS,
            details={"result_type": type(result).__name__},
        )

        return result


# Глобальный экземпляр анализатора
cognitive_analyzer = CognitiveAnalyzer()
