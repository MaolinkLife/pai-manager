# core/memory_layer.py

from typing import Dict, Any, List, Optional
import numpy as np
from datetime import datetime

from services import database_service, lorebook_service
from services.config_service import get_config_value
from services.logger_service import log_audit_entry, AuditStatus
from services.embed_service import get_embedding, Provider
from constants.memory import (
    SESSION_MEMORY_LIMIT,
    FALLBACK_RECENT_CONVERSATION,
    FALLBACK_HISTORICAL_CONTEXT,
)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot_product = sum(i * j for i, j in zip(a, b))
    magnitude_a = sum(i * i for i in a) ** 0.5
    magnitude_b = sum(i * i for i in b) ** 0.5
    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0
    return dot_product / (magnitude_a * magnitude_b)


class MemoryLayer:
    def __init__(self):
        self.session_memory_limit = SESSION_MEMORY_LIMIT
        self.threshold = 0.7  # можно из конфига

    async def get_context(self, current_message: Dict[str, Any]) -> Dict[str, Any]:
        try:
            user_content = current_message.get("content", "")
            user_embedding = get_embedding(user_content, provider=Provider.AUTO)

            if not user_embedding:
                log_audit_entry(
                    event_type="memory_layer.embed_error",
                    msg="[MemoryLayer] Failed to get embedding for user content.",
                    status=AuditStatus.ERROR,
                )
                return {
                    "key_facts": ["В ближайшей памяти не найдено."],
                    "session_length": 0,
                }

            # 1. Получить последние 32 сообщения
            recent_messages = self._get_recent_messages(limit=32)

            log_audit_entry(
                event_type="memory_layer.search_phase_1",
                msg="[MemoryLayer] Searching in recent messages (last 32).",
                status=AuditStatus.INFO,
                details={
                    "total_messages": len(recent_messages),
                    "threshold": self.threshold,
                },
            )

            # 2. Найти релевантные
            relevant_messages, scores = self._find_relevant_messages_with_scores(
                recent_messages, user_embedding, threshold=self.threshold
            )

            if relevant_messages:
                formatted_context = self._format_conversation(relevant_messages)
                log_audit_entry(
                    event_type="memory_layer.found_in_recent",
                    msg="[MemoryLayer] Found relevant messages in recent context.",
                    status=AuditStatus.INFO,
                    details={
                        "found_count": len(relevant_messages),
                        "scores": scores,
                        "content_preview": (
                            formatted_context[:200] + "..."
                            if len(formatted_context) > 200
                            else formatted_context
                        ),
                    },
                )
                return {
                    "key_facts": [formatted_context],
                    "session_length": len(relevant_messages),
                }

            # 3. Идём до начала сессии (до первого сообщения за сегодня)
            start_of_session = self._get_session_start(current_message.get("timestamp"))
            session_messages = self._get_messages_since(start_of_session)

            log_audit_entry(
                event_type="memory_layer.search_phase_2",
                msg="[MemoryLayer] Searching in session (since start of day).",
                status=AuditStatus.INFO,
                details={
                    "total_messages": len(session_messages),
                    "threshold": self.threshold,
                    "start_of_session": start_of_session,
                },
            )

            relevant_session, scores = self._find_relevant_messages_with_scores(
                session_messages, user_embedding, threshold=self.threshold
            )

            if relevant_session:
                formatted_context = self._format_conversation(relevant_session)
                first_message = relevant_session[0] if relevant_session else None
                log_audit_entry(
                    event_type="memory_layer.found_in_session",
                    msg="[MemoryLayer] Found relevant messages in session context.",
                    status=AuditStatus.INFO,
                    details={
                        "found_count": len(relevant_session),
                        "scores": scores,
                        "first_message_in_session": first_message,
                        "content_preview": (
                            formatted_context[:200] + "..."
                            if len(formatted_context) > 200
                            else formatted_context
                        ),
                    },
                )
                return {
                    "key_facts": [formatted_context],
                    "session_length": len(relevant_session),
                }

            # 4. Fallback
            log_audit_entry(
                event_type="memory_layer.fallback",
                msg="[MemoryLayer] No relevant messages found, using fallback.",
                status=AuditStatus.WARNING,
                details={
                    "total_messages_processed": len(recent_messages)
                    + len(session_messages),
                },
            )
            return {
                "key_facts": ["В ближайшей памяти не найдено."],
                "session_length": 0,
            }

        except Exception as e:
            log_audit_entry(
                event_type="memory_layer.error",
                msg=f"[MemoryLayer] Error in get_context: {e}",
                status=AuditStatus.ERROR,
                details={
                    "error": str(e),
                    "traceback": __import__("traceback").format_exc(),
                },
            )
            return {
                "key_facts": ["В ближайшей памяти не найдено."],
                "session_length": 0,
            }

    def _get_recent_messages(self, limit: int = 32) -> List[Dict]:
        char_name = get_config_value("char_name", "default_waifu")
        return database_service.get_history(char_name, limit)

    def _find_relevant_messages_with_scores(
        self, messages: List[Dict], user_embedding: List[float], threshold: float
    ) -> tuple[List[Dict], List[float]]:
        relevant = []
        scores = []
        total_processed = 0

        for msg in messages:
            content = msg.get("content", "")
            emb = get_embedding(content, provider=Provider.AUTO)
            if emb:
                sim = cosine_similarity(user_embedding, emb)
                total_processed += 1
                if sim >= threshold:
                    relevant.append(msg)
                    scores.append(sim)
            else:
                log_audit_entry(
                    event_type="memory_layer.embed_missing",
                    msg="[MemoryLayer] Failed to get embedding for message, skipping.",
                    status=AuditStatus.WARNING,
                    details={"message_content": content[:100]},
                )

        log_audit_entry(
            event_type="memory_layer.search_summary",
            msg="[MemoryLayer] Search completed.",
            status=AuditStatus.INFO,
            details={
                "total_messages_processed": total_processed,
                "total_relevant_found": len(relevant),
                "threshold_used": threshold,
                "max_similarity": max(scores) if scores else 0.0,
                "min_similarity": min(scores) if scores else 0.0,
            },
        )
        return relevant, scores

    def _get_session_start(self, timestamp: str) -> str:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        start_of_day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_of_day.isoformat()

    def _get_messages_since(self, start_time: str) -> List[Dict]:
        char_name = get_config_value("char_name", "default_waifu")
        return database_service.get_history_since(char_name, start_time)

    def _format_conversation(self, messages: List[Dict]) -> str:
        formatted = []
        for msg in messages:
            role = "User" if msg.get("role") == "user" else "Assistant"
            formatted.append(f"{role}: {msg.get('content', '')}")
        return "\n".join(formatted)

    async def get_lore_context(
        self,
        text: str,
        threshold: Optional[float] = None,
        top_k: Optional[int] = None,
    ) -> Dict[str, Any]:
        # твой старый метод — оставляем как есть
        try:
            if threshold is None:
                threshold = float(get_config_value("lorebook.similarityThreshold", 0.7))
            if top_k is None:
                top_k = int(get_config_value("lorebook.topK", 3))

            log_audit_entry(
                event_type="memory_layer.lore_query",
                msg="[MemoryLayer] Starting lore context search.",
                status=AuditStatus.INFO,
                details={"threshold": threshold, "top_k": top_k},
            )

            entries = lorebook_service.search_lore_entries(
                query=text,
                top_k=top_k,
                min_similarity=threshold,
            )

            top_results = []
            for entry in entries:
                title = entry.get("title") or ""
                content = entry.get("content") or ""
                phrase = f"{title}: {content}" if title else content
                top_results.append(phrase)

            log_audit_entry(
                event_type="memory_layer.lore_success",
                msg="[MemoryLayer] Lore context search completed.",
                status=AuditStatus.SUCCESS,
                details={
                    "matches_count": len(top_results),
                    "preview": top_results[:2],
                },
            )

            return {
                "lore_matches": top_results,
                "count": len(top_results),
                "raw_lore_entries": entries,
            }

        except Exception as e:
            log_audit_entry(
                event_type="memory_layer.lore_error",
                msg=f"[MemoryLayer] Lore context search failed: {e}",
                status=AuditStatus.ERROR,
                details={"error": str(e)},
            )
            return {"lore_matches": [], "count": 0, "raw_lore_entries": []}
