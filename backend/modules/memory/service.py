"""Memory module: encapsulates retrieval of conversational context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from services import database_service
from services.config_service import get_config_value
from services.logger_service import AuditStatus, log_audit_entry
from modules.memory.embeddings import Provider, get_embedding, get_embeddings
from modules.memory import lorebook

DEFAULT_RECENT_LIMIT = 32
DEFAULT_THRESHOLD = 0.7
DEFAULT_SESSION_WINDOW = "day"
DEFAULT_EMBED_PROVIDER = Provider.AUTO
DEFAULT_EMBED_MODEL = "nomic-embed-text"
DEFAULT_FALLBACK_MESSAGE = "За сегодня ничего не найдено."


@dataclass
class MemoryMatch:
    message_id: str
    role: str
    content: str
    timestamp: str
    score: float
    source: str = "recent"

    def formatted(self) -> str:
        role = "User" if self.role == "user" else "Assistant"
        ts = self.timestamp
        return f"{role} ({ts}): {self.content}" if ts else f"{role}: {self.content}"


@dataclass
class MemoryContextResult:
    context: Dict[str, Any]
    meta: Dict[str, Any] = field(default_factory=dict)


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = sum(a * a for a in vec_a) ** 0.5
    mag_b = sum(b * b for b in vec_b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class MemoryModule:
    """High-level orchestration for conversational memory retrieval."""

    async def collect_context(
        self, input_text: str, message_payload: Dict[str, Any]
    ) -> MemoryContextResult:
        settings = self._load_settings()
        char_name = get_config_value("char_name", "default_waifu")
        content = (input_text or "").strip()
        meta: Dict[str, Any] = {
            "settings": settings,
            "character": char_name,
        }

        log_audit_entry(
            "memory_module.start",
            "[Memory] Запрос на поиск контекста",
            AuditStatus.INFO,
            details={
                "character": char_name,
                "has_content": bool(content),
                "message_id": message_payload.get("id"),
            },
        )

        if not content:
            log_audit_entry(
                "memory_module.empty_input",
                "[Memory] Пустой ввод. Пропускаю поиск",
                AuditStatus.WARNING,
                details={"character": char_name},
            )
            return MemoryContextResult(
                context={
                    "key_facts": [DEFAULT_FALLBACK_MESSAGE],
                    "session_length": 0,
                    "memory_status": "empty_input",
                },
                meta=meta,
            )

        user_embedding = get_embedding(
            content,
            provider=settings["embedding_provider"],
            model=settings["embedding_model"],
        )

        if not user_embedding:
            log_audit_entry(
                "memory_module.embedding_failed",
                "[Memory] Не удалось получить эмбеддинг пользовательского ввода",
                AuditStatus.ERROR,
                details={"character": char_name},
            )
            return MemoryContextResult(
                context={
                    "key_facts": [DEFAULT_FALLBACK_MESSAGE],
                    "session_length": 0,
                    "memory_status": "embedding_failed",
                },
                meta=meta,
            )

        seen_ids: set[str] = set()
        best_match, recent_count = self._search_recent_history(
            char_name, user_embedding, seen_ids, settings
        )
        meta["recent_evaluated"] = recent_count

        if best_match is None and settings["session_enabled"]:
            best_match, session_count = self._search_session_history(
                char_name,
                user_embedding,
                seen_ids,
                settings,
                message_payload.get("timestamp"),
            )
            meta["session_evaluated"] = session_count

        if best_match:
            key_fact = best_match.formatted()
            meta.update(
                {
                    "memory_status": best_match.source,
                    "score": best_match.score,
                    "message_id": best_match.message_id,
                }
            )
            log_audit_entry(
                "memory_module.match_found",
                "[Memory] Найден релевантный фрагмент",
                AuditStatus.SUCCESS,
                details={
                    "score": best_match.score,
                    "source": best_match.source,
                    "message_id": best_match.message_id,
                },
            )
            return MemoryContextResult(
                context={
                    "key_facts": [key_fact],
                    "session_length": 1,
                    "memory_status": best_match.source,
                },
                meta=meta,
            )

        log_audit_entry(
            "memory_module.no_match",
            "[Memory] Релевантных сообщений не найдено",
            AuditStatus.INFO,
            details={"character": char_name},
        )
        meta["memory_status"] = "not_found"
        return MemoryContextResult(
            context={
                "key_facts": [DEFAULT_FALLBACK_MESSAGE],
                "session_length": 0,
                "memory_status": "not_found",
            },
            meta=meta,
        )

    async def collect_lore_context(self, text: str) -> Dict[str, Any]:
        try:
            threshold = float(get_config_value("lorebook.similarityThreshold", 0.7))
            top_k = int(get_config_value("lorebook.topK", 3))

            log_audit_entry(
                "memory_module.lore_query",
                "[Memory] Выполняю поиск по лорбуку",
                AuditStatus.INFO,
                details={"threshold": threshold, "top_k": top_k},
            )

            entries = lorebook.search_entries(
                query=text,
                top_k=top_k,
                min_similarity=threshold,
            )

            formatted = []
            for entry in entries:
                title = entry.get("title") or ""
                content = entry.get("content") or ""
                phrase = f"{title}: {content}" if title else content
                if phrase:
                    formatted.append(phrase)

            log_audit_entry(
                "memory_module.lore_success",
                "[Memory] Лор найден",
                AuditStatus.SUCCESS,
                details={"count": len(formatted)},
            )

            return {
                "lore_matches": formatted,
                "count": len(formatted),
                "raw_lore_entries": entries,
            }

        except Exception as exc:  # pragma: no cover
            log_audit_entry(
                "memory_module.lore_error",
                "[Memory] Ошибка поиска по лорбуку",
                AuditStatus.ERROR,
                details={"error": str(exc)},
            )
            return {"lore_matches": [], "count": 0, "raw_lore_entries": []}

    def _load_settings(self) -> Dict[str, Any]:
        return {
            "recent_limit": int(get_config_value("memory.recent_limit", DEFAULT_RECENT_LIMIT)),
            "similarity_threshold": float(
                get_config_value("memory.similarity_threshold", DEFAULT_THRESHOLD)
            ),
            "session_window": get_config_value("memory.session_window", DEFAULT_SESSION_WINDOW),
            "session_enabled": bool(
                get_config_value("memory.session_enabled", True)
            ),
            "embedding_provider": (
                get_config_value("memory.embedding_provider", DEFAULT_EMBED_PROVIDER)
                or DEFAULT_EMBED_PROVIDER
            ),
            "embedding_model": (
                get_config_value("memory.embedding_model", DEFAULT_EMBED_MODEL)
                or DEFAULT_EMBED_MODEL
            ),
        }

    def _search_recent_history(
        self,
        character: str,
        user_embedding: List[float],
        seen_ids: set[str],
        settings: Dict[str, Any],
    ) -> tuple[Optional[MemoryMatch], int]:
        recent_limit = settings["recent_limit"]
        threshold = settings["similarity_threshold"]
        provider = settings["embedding_provider"]
        model = settings["embedding_model"]

        recent_messages = database_service.get_history(character, limit=recent_limit)
        if not recent_messages:
            return None, 0

        log_audit_entry(
            "memory_module.recent_search",
            "[Memory] Поиск в последних сообщениях",
            AuditStatus.INFO,
            details={"count": len(recent_messages), "threshold": threshold},
        )

        match = self._find_best_match(
            recent_messages,
            user_embedding,
            threshold,
            provider,
            model,
            source="recent",
            seen_ids=seen_ids,
        )
        return match, len(recent_messages)

    def _search_session_history(
        self,
        character: str,
        user_embedding: List[float],
        seen_ids: set[str],
        settings: Dict[str, Any],
        timestamp: Optional[str],
    ) -> tuple[Optional[MemoryMatch], int]:
        start_time = self._compute_session_start(timestamp, settings["session_window"])
        session_messages = database_service.get_history_since(character, start_time)
        if not session_messages:
            return None, 0

        log_audit_entry(
            "memory_module.session_search",
            "[Memory] Поиск в пределах сессии",
            AuditStatus.INFO,
            details={
                "messages": len(session_messages),
                "start_time": start_time,
                "threshold": settings["similarity_threshold"],
            },
        )

        match = self._find_best_match(
            session_messages,
            user_embedding,
            settings["similarity_threshold"],
            settings["embedding_provider"],
            settings["embedding_model"],
            source="session",
            seen_ids=seen_ids,
        )
        return match, len(session_messages)

    def _find_best_match(
        self,
        messages: List[Dict[str, Any]],
        user_embedding: List[float],
        threshold: float,
        provider: str,
        model: str,
        *,
        source: str,
        seen_ids: set[str],
    ) -> Optional[MemoryMatch]:
        texts: List[str] = []
        mapping: List[Dict[str, Any]] = []
        for msg in messages:
            msg_id = msg.get("id")
            content = (msg.get("content") or "").strip()
            if not content or (msg_id and msg_id in seen_ids):
                continue
            texts.append(content)
            mapping.append(msg)
            if msg_id:
                seen_ids.add(msg_id)

        if not texts:
            return None

        embeddings = get_embeddings(texts, provider=provider, model=model)
        best: Optional[MemoryMatch] = None
        for msg, emb in zip(mapping, embeddings):
            if not emb:
                continue
            score = _cosine_similarity(user_embedding, emb)
            if score < threshold:
                continue
            if best is None or score > best.score:
                best = MemoryMatch(
                    message_id=msg.get("id", ""),
                    role=msg.get("role", "assistant"),
                    content=msg.get("content", ""),
                    timestamp=msg.get("timestamp", ""),
                    score=score,
                    source=source,
                )

        return best

    @staticmethod
    def _compute_session_start(timestamp: Optional[str], window: str) -> str:
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except Exception:
                dt = datetime.now(timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        if window == "day":
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)

        return dt.isoformat()
