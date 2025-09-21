# core/memory_layer.py
from typing import Dict, Any, List
import numpy as np
import traceback

from services import database_service, embed_service
from services.logger_service import log_audit_entry, AuditStatus
from constants.memory import (
    SESSION_MEMORY_LIMIT,
    FALLBACK_RECENT_CONVERSATION,
    FALLBACK_HISTORICAL_CONTEXT,
)


class MemoryLayer:
    """
    MemoryLayer manages session memory and lorebook retrieval.
    Provides:
    - Recent conversation context (session memory)
    - Relevant knowledge from lorebook (embedding similarity search)
    """

    def __init__(self):
        self.session_memory_limit = SESSION_MEMORY_LIMIT

    async def get_context(self, current_message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Collect recent context from session memory.

        Args:
            current_message: Current incoming user message

        Returns:
            Dictionary with recent conversation, historical context and session length
        """
        try:
            log_audit_entry(
                event_type="memory_layer.processing",
                msg="[MemoryLayer] Collecting session context.",
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

            # Lazy import to avoid circular dependencies
            from services.database_service import get_history
            from services.config_service import get_config_value

            char_name = get_config_value("char_name", "default_waifu")

            log_audit_entry(
                event_type="memory_layer.db_query",
                msg="[MemoryLayer] Requesting history from DB.",
                status=AuditStatus.INFO,
                details={
                    "character_name": char_name,
                    "limit": self.session_memory_limit,
                },
            )

            # Fetch recent messages from DB
            recent_messages = get_history(char_name, self.session_memory_limit)

            log_audit_entry(
                event_type="memory_layer.db_result",
                msg="[MemoryLayer] History fetched from DB.",
                status=AuditStatus.INFO,
                details={
                    "messages_count": len(recent_messages),
                    "character_name": char_name,
                },
            )

            # Format conversation
            recent_conversation = self._format_recent_conversation(recent_messages)

            result = {
                "recent_conversation": recent_conversation,
                "historical_context": FALLBACK_HISTORICAL_CONTEXT,
                "session_length": len(recent_messages),
            }

            conversation_preview = (
                result["recent_conversation"][:100] + "..."
                if len(result["recent_conversation"]) > 100
                else result["recent_conversation"]
            )
            log_audit_entry(
                event_type="memory_layer.completed",
                msg="[MemoryLayer] Session context successfully built.",
                status=AuditStatus.SUCCESS,
                details={
                    "session_length": result["session_length"],
                    "conversation_preview": conversation_preview,
                },
            )

            return result

        except Exception as e:
            error_msg = (
                f"[MemoryLayer] Error while retrieving session context: {str(e)}"
            )
            print(error_msg)
            traceback.print_exc()

            log_audit_entry(
                event_type="memory_layer.error",
                msg=error_msg,
                status=AuditStatus.ERROR,
                details={
                    "error": str(e),
                    "traceback": traceback.format_exc()[:500],
                },
            )

            # Fallback context
            return {
                "recent_conversation": FALLBACK_RECENT_CONVERSATION,
                "historical_context": FALLBACK_HISTORICAL_CONTEXT,
                "session_length": 1,
            }

    def _format_recent_conversation(self, messages: List[Dict]) -> str:
        """
        Format recent conversation into readable string.

        Args:
            messages: List of messages with role/content

        Returns:
            String with formatted dialogue
        """
        if not messages:
            return FALLBACK_RECENT_CONVERSATION

        formatted = []
        for msg in messages:
            role = "User" if msg.get("role") == "user" else "Lim"
            formatted.append(f"{role}: {msg.get('content', '')}")

        return "\n".join(formatted)

    async def get_lore_context(
        self, text: str, threshold: float = 0.7, top_k: int = 3
    ) -> Dict[str, Any]:
        """
        Retrieve relevant knowledge from lorebook using embeddings.

        Args:
            text: Input text query
            threshold: Similarity threshold
            top_k: Maximum number of top matches

        Returns:
            Dictionary with lore matches and their count
        """
        try:
            log_audit_entry(
                event_type="memory_layer.lore_query",
                msg="[MemoryLayer] Starting lore context search.",
                status=AuditStatus.INFO,
                details={"threshold": threshold, "top_k": top_k},
            )

            query_emb = embed_service.get_embedding(text)
            lore_entries = database_service.get_lorebook()  # [{id, content, embedding}]

            results = []
            for entry in lore_entries:
                emb = np.array(entry["embedding"])
                sim = self._cosine_similarity(query_emb, emb)
                if sim >= threshold:
                    results.append((sim, entry["content"]))

            results.sort(key=lambda x: x[0], reverse=True)
            top_results = [content for _, content in results[:top_k]]

            log_audit_entry(
                event_type="memory_layer.lore_success",
                msg="[MemoryLayer] Lore context search completed.",
                status=AuditStatus.SUCCESS,
                details={"matches_count": len(top_results)},
            )

            return {"lore_matches": top_results, "count": len(top_results)}

        except Exception as e:
            log_audit_entry(
                event_type="memory_layer.lore_error",
                msg=f"[MemoryLayer] Lore context search failed: {e}",
                status=AuditStatus.ERROR,
                details={"error": str(e)},
            )
            return {"lore_matches": [], "count": 0}

    def _cosine_similarity(self, a, b) -> float:
        """
        Compute cosine similarity between two vectors.

        Args:
            a: First vector
            b: Second vector

        Returns:
            Cosine similarity score (float)
        """
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
