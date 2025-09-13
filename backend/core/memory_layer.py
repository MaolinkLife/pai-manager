# core/memory_layer.py
from typing import Dict, Any, List
from datetime import datetime, timedelta
import asyncio

# Импортируем логгер в начале файла
from services.logger_service import log_audit_entry, AuditStatus


class MemoryLayer:
    def __init__(self):
        self.session_memory_limit = 32  # последние 32 сообщения

    async def get_context(self, current_message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Получаем контекст из памяти - последние 32 сообщения
        """
        try:
            # Логируем начало процесса
            log_audit_entry(
                event_type="memory_layer.processing",
                msg="[MemoryLayer] Начало получения контекста из памяти",
                status=AuditStatus.INFO,
                details={
                    "session_memory_limit": self.session_memory_limit,
                    "current_message_preview": (
                        current_message.get("content", "")[:50]
                        if current_message and current_message.get("content")
                        else "No content"
                    ),
                },
            )

            # Импортируем здесь, чтобы избежать циклических импортов
            from services.database_service import get_history
            from services.config_service import get_config_value

            char_name = get_config_value("char_name", "default_waifu")

            # Логируем попытку получения истории
            log_audit_entry(
                event_type="memory_layer.db_query",
                msg="[MemoryLayer] Запрос истории из базы данных",
                status=AuditStatus.INFO,
                details={
                    "character_name": char_name,
                    "limit": self.session_memory_limit,
                },
            )

            # Получаем последние 32 сообщения из БД
            recent_messages = get_history(char_name, self.session_memory_limit)

            # Логируем результат запроса
            log_audit_entry(
                event_type="memory_layer.db_result",
                msg="[MemoryLayer] Получена история из базы данных",
                status=AuditStatus.INFO,
                details={
                    "messages_count": len(recent_messages),
                    "character_name": char_name,
                },
            )

            # Форматируем диалог
            recent_conversation = self._format_recent_conversation(recent_messages)

            result = {
                "recent_conversation": recent_conversation,
                "historical_context": "Общая история взаимодействий (доступна при глубокой памяти)...",
                "session_length": len(recent_messages),
            }

            # Логируем финальный результат
            conversation_preview = (
                result["recent_conversation"][:100] + "..."
                if len(result["recent_conversation"]) > 100
                else result["recent_conversation"]
            )
            log_audit_entry(
                event_type="memory_layer.completed",
                msg="[MemoryLayer] Контекст успешно собран",
                status=AuditStatus.SUCCESS,
                details={
                    "session_length": result["session_length"],
                    "conversation_preview": conversation_preview,
                },
            )

            return result

        except Exception as e:
            error_msg = f"[MemoryLayer] Ошибка получения контекста: {str(e)}"
            print(error_msg)
            import traceback

            traceback.print_exc()

            # Логируем ошибку
            log_audit_entry(
                event_type="memory_layer.error",
                msg=error_msg,
                status=AuditStatus.ERROR,
                details={
                    "error": str(e),
                    "traceback": traceback.format_exc()[
                        :500
                    ],  # Ограничиваем длину трейсбэка
                },
            )

            # Возвращаем заглушку в случае ошибки
            return {
                "recent_conversation": "Вы только начали диалог.",
                "historical_context": "Общая история взаимодействий...",
                "session_length": 1,
            }

    def _format_recent_conversation(self, messages: List[Dict]) -> str:
        """Форматируем недавний диалог"""
        if not messages:
            return "Вы только начали диалог."

        formatted = []
        for msg in messages:
            role = "Пользователь" if msg.get("role") == "user" else "Лим"
            formatted.append(f"{role}: {msg.get('content', '')}")

        return "\n".join(formatted)
