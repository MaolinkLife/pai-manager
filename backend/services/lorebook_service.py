"""Lorebook management backed by the relational database and vector store."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from models.models import LorebookEntry
from services.db_core import SessionLocal
from services import embed_service, vector_service
from services.logger_service import log_audit_entry, AuditStatus

# Убираем старую константу, теперь используем две коллекции
LOREBOOK_COLLECTION_384 = "pai_lorebook_384"
LOREBOOK_COLLECTION_768 = "pai_lorebook_768"

DEFAULT_ENTRIES: List[Dict[str, Any]] = [
    {
        "title": "Title Theme",
        "content": ("Content here..."),
        "keywords": "keywords",
        "category": "categhory",
    }
]


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _entry_to_dict(entry: LorebookEntry) -> Dict[str, Any]:
    return {
        "id": entry.id,
        "title": entry.title,
        "content": entry.content,
        "keywords": entry.keywords,
        "category": entry.category,
        "active": entry.active,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


def _compose_document(entry: LorebookEntry) -> str:
    parts = [entry.title or "", entry.content or "", entry.keywords or ""]
    return "\n".join(part.strip() for part in parts if part)


def _upsert_embedding(entry: LorebookEntry) -> None:
    """Добавляем эмбеддинги в ОБЕ коллекции"""
    text = _compose_document(entry)
    if not text:
        return

    try:
        # Получаем оба эмбеддинга
        embedding_384 = embed_service.get_embedding_st(text)
        embedding_768 = embed_service.get_embedding_ollama(text)

        metadata = {
            "title": entry.title,
            "category": entry.category,
            "active": entry.active,
        }

        # Добавляем в коллекцию 384
        if embedding_384:
            vector_service.upsert_text(
                doc_id=str(entry.id),
                text=text,
                embedding=embedding_384,
                metadata={**metadata, "dimension": 384},
                collection_name=LOREBOOK_COLLECTION_384,
            )

        # Добавляем в коллекцию 768
        if embedding_768:
            vector_service.upsert_text(
                doc_id=str(entry.id),
                text=text,
                embedding=embedding_768,
                metadata={**metadata, "dimension": 768},
                collection_name=LOREBOOK_COLLECTION_768,
            )

    except Exception as e:
        log_audit_entry(
            event_type="lorebook_embedding_error",
            msg="[Lorebook] Failed to upsert embeddings",
            status=AuditStatus.ERROR,
            details={"entry_id": entry.id, "error": str(e)},
        )


def _delete_embedding(entry_id: int) -> None:
    """Удаляем из обеих коллекций"""
    try:
        vector_service.delete_text(
            str(entry_id), collection_name=LOREBOOK_COLLECTION_384
        )
        vector_service.delete_text(
            str(entry_id), collection_name=LOREBOOK_COLLECTION_768
        )
    except Exception as e:
        log_audit_entry(
            event_type="lorebook_delete_error",
            msg="[Lorebook] Failed to delete embeddings",
            status=AuditStatus.ERROR,
            details={"entry_id": entry_id, "error": str(e)},
        )


def _ensure_defaults(session: Session) -> None:
    existing = {entry.title: entry for entry in session.query(LorebookEntry).all()}

    changed = False
    for payload in DEFAULT_ENTRIES:
        entry = existing.get(payload["title"])
        if entry:
            updated_values = False
            for field in ["content", "keywords", "category"]:
                new_value = payload.get(field)
                if new_value is not None and getattr(entry, field) != new_value:
                    setattr(entry, field, new_value)
                    updated_values = True
            if updated_values:
                changed = True
        else:
            entry = LorebookEntry(
                title=payload["title"],
                content=payload["content"],
                keywords=payload.get("keywords", ""),
                category=payload.get("category", "general"),
                active=payload.get("active", True),
            )
            session.add(entry)
            changed = True

    if changed:
        session.commit()

    session.expire_all()
    for entry in session.query(LorebookEntry).all():
        _upsert_embedding(entry)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_lorebook_entries() -> List[Dict[str, Any]]:
    session: Session = SessionLocal()
    try:
        _ensure_defaults(session)
        entries = session.query(LorebookEntry).order_by(LorebookEntry.id.asc()).all()
        return [_entry_to_dict(entry) for entry in entries]
    finally:
        session.close()


def add_lorebook_entry(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    session: Session = SessionLocal()
    try:
        lore_entry = LorebookEntry(
            title=entry.get("title") or "Untitled",
            content=entry.get("content", ""),
            keywords=entry.get("keywords", ""),
            category=entry.get("category", "general"),
            active=entry.get("active", True),
        )
        session.add(lore_entry)
        session.commit()
        session.refresh(lore_entry)

        _upsert_embedding(lore_entry)
        return _entry_to_dict(lore_entry)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def update_lorebook_entry(
    entry_id: int, data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    session: Session = SessionLocal()
    try:
        entry = session.query(LorebookEntry).filter_by(id=entry_id).first()
        if not entry:
            return None

        entry.title = data.get("title", entry.title)
        entry.content = data.get("content", entry.content)
        entry.keywords = data.get("keywords", entry.keywords)
        entry.category = data.get("category", entry.category)
        entry.active = data.get("active", entry.active)

        session.commit()
        session.refresh(entry)

        _upsert_embedding(entry)
        return _entry_to_dict(entry)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def delete_lorebook_entry(entry_id: int) -> bool:
    session: Session = SessionLocal()
    try:
        entry = session.query(LorebookEntry).filter_by(id=entry_id).first()
        if not entry:
            return False

        session.delete(entry)
        session.commit()
        _delete_embedding(entry_id)
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _get_configured(path: str, fallback):
    # Заглушка для конфигурации, если не используется
    return fallback


def _normalize_weights(
    vector_weight: float, keyword_weight: float
) -> tuple[float, float]:
    total = vector_weight + keyword_weight
    if total <= 0:
        return 1.0, 0.0
    return vector_weight / total, keyword_weight / total


def search_lore_entries(
    query: str,
    top_k: Optional[int] = None,
    min_similarity: Optional[float] = None,
    use_keyword_fallback: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    session: Session = SessionLocal()
    try:
        _ensure_defaults(session)

        if top_k is None:
            top_k = 5
        if min_similarity is None:
            min_similarity = 0.7
        if use_keyword_fallback is None:
            use_keyword_fallback = False

        if not query.strip():
            return get_lorebook_entries()

        # Сначала пробуем поиск в коллекции 768 (приоритет)
        try:
            embedding_768 = embed_service.get_embedding_ollama(query)
            if embedding_768:
                results_768 = vector_service.search(
                    query_embedding=embedding_768,
                    top_k=top_k,
                    collection_name=LOREBOOK_COLLECTION_768,
                )
                matches_768 = _process_search_results(
                    session, results_768, min_similarity
                )
                if matches_768:
                    log_audit_entry(
                        event_type="lorebook_vector_matches",
                        msg="[Lorebook] Vector matches retrieved (768-dim)",
                        status=AuditStatus.INFO,
                        details={
                            "query": query,
                            "matches": [
                                {
                                    "id": m.get("id"),
                                    "title": m.get("title"),
                                    "similarity": m.get("similarity"),
                                }
                                for m in matches_768
                            ],
                        },
                    )
                    return matches_768
        except Exception as e:
            log_audit_entry(
                event_type="lorebook_search_768_error",
                msg="[Lorebook] Search in 768 collection failed",
                status=AuditStatus.WARNING,
                details={"query": query, "error": str(e)},
            )

        # Фолбэк на коллекцию 384
        try:
            embedding_384 = embed_service.get_embedding_st(query)
            if embedding_384:
                results_384 = vector_service.search(
                    query_embedding=embedding_384,
                    top_k=top_k,
                    collection_name=LOREBOOK_COLLECTION_384,
                )
                matches_384 = _process_search_results(
                    session, results_384, min_similarity
                )
                if matches_384:
                    log_audit_entry(
                        event_type="lorebook_vector_matches",
                        msg="[Lorebook] Vector matches retrieved (384-dim)",
                        status=AuditStatus.INFO,
                        details={
                            "query": query,
                            "matches": [
                                {
                                    "id": m.get("id"),
                                    "title": m.get("title"),
                                    "similarity": m.get("similarity"),
                                }
                                for m in matches_384
                            ],
                        },
                    )
                    return matches_384
        except Exception as e:
            log_audit_entry(
                event_type="lorebook_search_384_error",
                msg="[Lorebook] Search in 384 collection failed",
                status=AuditStatus.ERROR,
                details={"query": query, "error": str(e)},
            )

        # Если оба поиска неудачны, фолбэк на keyword search
        log_audit_entry(
            event_type="lorebook_zero_matches",
            msg="[Lorebook] No vector matches found, using keyword fallback",
            status=AuditStatus.INFO,
            details={"query": query},
        )
        return _keyword_fallback(session, query, top_k) if use_keyword_fallback else []

    finally:
        session.close()


def _process_search_results(
    session: Session, results: Dict, min_similarity: float
) -> List[Dict[str, Any]]:
    """Обрабатываем результаты поиска из векторной коллекции"""
    matches: List[Dict[str, Any]] = []
    ids = results.get("ids", [[]])[0]
    distances = results.get("distances", [[1.0]])[0]
    metadatas = results.get("metadatas", [[]])[0]

    for doc_id, distance in zip(ids, distances):
        if doc_id is None:
            continue

        similarity = 1 - float(distance)
        if similarity < min_similarity:
            continue

        try:
            entry_id = int(doc_id)
        except (TypeError, ValueError):
            continue

        entry = session.query(LorebookEntry).filter_by(id=entry_id).first()
        if entry and entry.active:
            entry_dict = _entry_to_dict(entry)
            entry_dict["similarity"] = similarity
            matches.append(entry_dict)

    return matches


def _keyword_fallback(
    session: Session, query: str, top_k: int = 5
) -> List[Dict[str, Any]]:
    query_lower = query.lower()
    query_tokens = set(filter(None, __tokenize(query_lower)))
    results: List[Dict[str, Any]] = []

    for entry in (
        session.query(LorebookEntry)
        .filter(LorebookEntry.active == True)  # noqa: E712
        .all()
    ):
        haystack = " ".join(
            filter(
                None,
                [entry.title, entry.content, entry.keywords, entry.category],
            )
        ).lower()
        entry_tokens = set(filter(None, __tokenize(haystack)))
        if query_lower in haystack or query_tokens & entry_tokens:
            results.append(_entry_to_dict(entry))
            if len(results) >= top_k:
                break

    return results


def __tokenize(text: str) -> List[str]:
    import re

    return re.findall(r"[\w\-]+", text)
