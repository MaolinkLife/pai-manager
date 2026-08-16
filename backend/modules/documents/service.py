"""Knowledge collections: CRUD, indexing pipeline and retrieval.

A collection maps to one Chroma collection (``kb_<id>``). Files come from
the library (Storage rows); indexing extracts text, splits it into chunks
and embeds them with the provider pinned on the collection ('ollama'
768-dim or 'st' sentence-transformers) so the whole collection shares one
embedding space. Retrieval returns chunks with file-level sources for
citations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session, joinedload

from models.models import KnowledgeCollection, KnowledgeFile
from modules.database.core import SessionLocal
from modules.documents.extractors import (
    ExtractionError,
    extract_text,
    split_into_chunks,
    supported_for_indexing,
)
from modules.memory import embeddings, vector as vector_service
from modules.storage.service import get_media_entry, resolve_media_path
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry
from utils.time_utils import to_user_tz_iso


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _settings() -> Dict[str, Any]:
    cfg = config_service.get_config_value("documents", {}) or {}
    return {
        "enabled": bool(cfg.get("enabled", True)),
        "chunk_size": int(cfg.get("chunk_size", 1200) or 1200),
        "chunk_overlap": int(cfg.get("chunk_overlap", 150) or 150),
        "top_k": int(cfg.get("top_k", 4) or 4),
        "min_similarity": float(cfg.get("min_similarity", 0.35) or 0.35),
        "max_context_chars": int(cfg.get("max_context_chars", 2400) or 2400),
    }


def _chroma_name(collection_id: str) -> str:
    return f"kb_{collection_id}"


# ---------------------------------------------------------------------------
# Embeddings (provider pinned per collection)
# ---------------------------------------------------------------------------

def _resolve_provider() -> str:
    probe = embeddings.get_embedding_ollama("ping")
    return "ollama" if probe else "st"


def _embed_texts(texts: List[str], provider: str) -> List[Optional[List[float]]]:
    if provider == "ollama":
        return embeddings.get_embeddings_ollama(texts)
    return embeddings.get_embeddings_st(texts)


def _embed_query(text: str, provider: str) -> Optional[List[float]]:
    if provider == "ollama":
        return embeddings.get_embedding_ollama(text)
    return embeddings.get_embedding_st(text)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def _serialize_collection(row: KnowledgeCollection, file_count: int | None = None) -> Dict[str, Any]:
    files = list(row.files or []) if file_count is None else None
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "enabled": bool(row.enabled),
        "embedding_provider": row.embedding_provider or "",
        "file_count": len(files) if files is not None else int(file_count or 0),
        "created_at": to_user_tz_iso(row.created_at),
        "updated_at": to_user_tz_iso(row.updated_at),
    }


def _serialize_file(row: KnowledgeFile) -> Dict[str, Any]:
    return {
        "id": row.id,
        "collection_id": row.collection_id,
        "media_id": row.media_id,
        "name": row.name,
        "mime_type": row.mime_type,
        "size": int(row.size or 0),
        "status": row.status,
        "error": row.error or "",
        "chunk_count": int(row.chunk_count or 0),
        "indexed_at": to_user_tz_iso(row.indexed_at) if row.indexed_at else None,
        "created_at": to_user_tz_iso(row.created_at),
    }


# ---------------------------------------------------------------------------
# Collections CRUD
# ---------------------------------------------------------------------------

def list_collections() -> List[Dict[str, Any]]:
    session: Session = SessionLocal()
    try:
        rows = (
            session.query(KnowledgeCollection)
            .options(joinedload(KnowledgeCollection.files))
            .order_by(KnowledgeCollection.created_at.desc())
            .all()
        )
        return [_serialize_collection(row) for row in rows]
    finally:
        session.close()


def create_collection(name: str, description: str = "") -> Dict[str, Any]:
    name = str(name or "").strip()
    if not name:
        raise ValueError("Collection name is required")
    session: Session = SessionLocal()
    try:
        row = KnowledgeCollection(
            id=str(uuid.uuid4()),
            name=name,
            description=str(description or "").strip(),
            enabled=True,
            created_at=_now(),
            updated_at=_now(),
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return _serialize_collection(row, file_count=0)
    finally:
        session.close()


def update_collection(collection_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    session: Session = SessionLocal()
    try:
        row = session.query(KnowledgeCollection).filter_by(id=collection_id).first()
        if not row:
            return None
        if "name" in fields and str(fields["name"] or "").strip():
            row.name = str(fields["name"]).strip()
        if "description" in fields and fields["description"] is not None:
            row.description = str(fields["description"]).strip()
        if "enabled" in fields and fields["enabled"] is not None:
            row.enabled = bool(fields["enabled"])
        row.updated_at = _now()
        session.commit()
        session.refresh(row)
        return _serialize_collection(row)
    finally:
        session.close()


def delete_collection(collection_id: str) -> bool:
    session: Session = SessionLocal()
    try:
        row = session.query(KnowledgeCollection).filter_by(id=collection_id).first()
        if not row:
            return False
        session.delete(row)
        session.commit()
    finally:
        session.close()
    try:
        vector_service.reset(_chroma_name(collection_id))
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def list_files(collection_id: str) -> List[Dict[str, Any]]:
    session: Session = SessionLocal()
    try:
        rows = (
            session.query(KnowledgeFile)
            .filter_by(collection_id=collection_id)
            .order_by(KnowledgeFile.created_at.desc())
            .all()
        )
        return [_serialize_file(row) for row in rows]
    finally:
        session.close()


def add_file_from_library(collection_id: str, media_id: str) -> Dict[str, Any]:
    entry = get_media_entry(media_id)
    name = str(getattr(entry, "file_name", "") or "file")
    mime = str(getattr(entry, "mime_type", "") or "text/plain")
    if not supported_for_indexing(name, mime):
        raise ValueError(f"File type is not supported for indexing: {name}")

    session: Session = SessionLocal()
    try:
        collection = session.query(KnowledgeCollection).filter_by(id=collection_id).first()
        if not collection:
            raise ValueError("Collection not found")
        duplicate = (
            session.query(KnowledgeFile)
            .filter_by(collection_id=collection_id, media_id=media_id)
            .first()
        )
        if duplicate:
            return _serialize_file(duplicate)

        row = KnowledgeFile(
            id=str(uuid.uuid4()),
            collection_id=collection_id,
            media_id=media_id,
            name=name,
            mime_type=mime,
            size=int(getattr(entry, "size", 0) or 0),
            status="pending",
            created_at=_now(),
        )
        session.add(row)
        collection.updated_at = _now()
        session.commit()
        session.refresh(row)
        file_id = row.id
    finally:
        session.close()

    return index_file(file_id)


def index_file(file_id: str) -> Dict[str, Any]:
    """Extract → chunk → embed → store. Never raises: failures land in the
    file row as status='error' so the UI can show what went wrong."""
    settings = _settings()
    session: Session = SessionLocal()
    try:
        row = session.query(KnowledgeFile).filter_by(id=file_id).first()
        if not row:
            raise ValueError("File not found")
        collection = session.query(KnowledgeCollection).filter_by(id=row.collection_id).first()
        if not collection:
            raise ValueError("Collection not found")
        collection_id = collection.id
        provider = collection.embedding_provider or ""
        media_id = row.media_id
        name = row.name
        mime = row.mime_type
    finally:
        session.close()

    chunk_count = 0
    error = ""
    try:
        entry = get_media_entry(media_id)
        path = resolve_media_path(entry)
        raw = path.read_bytes()
        text = extract_text(raw, name=name, mime_type=mime)
        chunks = split_into_chunks(
            text,
            chunk_size=settings["chunk_size"],
            overlap=settings["chunk_overlap"],
        )
        if not chunks:
            raise ExtractionError("No indexable text in the file")

        if not provider:
            provider = _resolve_provider()

        vectors = _embed_texts(chunks, provider)
        documents: List[str] = []
        embeddings_list: List[List[float]] = []
        ids: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            if not vector:
                continue
            documents.append(chunk)
            embeddings_list.append(vector)
            ids.append(f"{file_id}::{index}")
            metadatas.append({
                "file_id": file_id,
                "file_name": name,
                "collection_id": collection_id,
                "chunk_index": index,
            })
        if not documents:
            raise ExtractionError("Embedding provider returned no vectors")

        # Re-index = replace: drop previous chunks of this file first.
        _delete_file_chunks(collection_id, file_id)
        vector_service.add_texts(
            documents,
            embeddings_list,
            metadatas=metadatas,
            ids=ids,
            collection_name=_chroma_name(collection_id),
        )
        chunk_count = len(documents)
    except Exception as exc:
        error = str(exc)

    session = SessionLocal()
    try:
        row = session.query(KnowledgeFile).filter_by(id=file_id).first()
        if not row:
            raise ValueError("File not found")
        if error:
            row.status = "error"
            row.error = error[:2000]
        else:
            row.status = "indexed"
            row.error = ""
            row.chunk_count = chunk_count
            row.indexed_at = _now()
            collection = session.query(KnowledgeCollection).filter_by(id=row.collection_id).first()
            if collection and not collection.embedding_provider:
                collection.embedding_provider = provider
        session.commit()
        session.refresh(row)
        payload = _serialize_file(row)
    finally:
        session.close()

    log_audit_entry(
        "knowledge_file_indexed" if not error else "knowledge_file_index_failed",
        "[Documents] File indexing finished.",
        AuditStatus.INFO if not error else AuditStatus.WARNING,
        details={"file_id": file_id, "chunks": chunk_count, "error": error or None},
    )
    return payload


def remove_file(file_id: str) -> bool:
    session: Session = SessionLocal()
    try:
        row = session.query(KnowledgeFile).filter_by(id=file_id).first()
        if not row:
            return False
        collection_id = row.collection_id
        session.delete(row)
        session.commit()
    finally:
        session.close()
    _delete_file_chunks(collection_id, file_id)
    return True


def reindex_collection(collection_id: str) -> List[Dict[str, Any]]:
    session: Session = SessionLocal()
    try:
        ids = [
            row.id
            for row in session.query(KnowledgeFile).filter_by(collection_id=collection_id).all()
        ]
    finally:
        session.close()
    return [index_file(file_id) for file_id in ids]


def _delete_file_chunks(collection_id: str, file_id: str) -> None:
    try:
        collection = vector_service._get_collection(_chroma_name(collection_id))
        collection.delete(where={"file_id": file_id})
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def search(query: str, *, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
    """Search enabled collections; returns chunks with similarity + source."""
    settings = _settings()
    if not settings["enabled"]:
        return []
    query = str(query or "").strip()
    if not query:
        return []

    session: Session = SessionLocal()
    try:
        collections = (
            session.query(KnowledgeCollection)
            .filter_by(enabled=True)
            .all()
        )
        targets = [
            (row.id, row.name, row.embedding_provider)
            for row in collections
            if row.embedding_provider
        ]
    finally:
        session.close()
    if not targets:
        return []

    limit = top_k or settings["top_k"]
    matches: List[Dict[str, Any]] = []
    query_cache: Dict[str, Optional[List[float]]] = {}

    for collection_id, collection_name, provider in targets:
        if provider not in query_cache:
            query_cache[provider] = _embed_query(query, provider)
        vector = query_cache[provider]
        if not vector:
            continue
        try:
            results = vector_service.search(
                vector, top_k=limit, collection_name=_chroma_name(collection_id)
            )
        except Exception:
            continue
        documents = (results.get("documents") or [[]])[0]
        metadatas = (results.get("metadatas") or [[]])[0]
        distances = (results.get("distances") or [[]])[0]
        for document, metadata, distance in zip(documents, metadatas, distances):
            similarity = 1.0 - float(distance)
            if similarity < settings["min_similarity"]:
                continue
            matches.append({
                "text": document,
                "similarity": round(similarity, 4),
                "collection_id": collection_id,
                "collection_name": collection_name,
                "file_id": (metadata or {}).get("file_id"),
                "file_name": (metadata or {}).get("file_name") or "",
                "chunk_index": (metadata or {}).get("chunk_index"),
            })

    matches.sort(key=lambda item: -item["similarity"])
    return matches[:limit]


def build_context_block(query: str) -> Optional[Dict[str, Any]]:
    """Top matches formatted for the instructor tool block + sources list."""
    settings = _settings()
    matches = search(query)
    if not matches:
        return None

    budget = settings["max_context_chars"]
    parts: List[str] = []
    sources: List[Dict[str, Any]] = []
    used = 0
    for match in matches:
        snippet = match["text"].strip()
        if used + len(snippet) > budget and parts:
            break
        snippet = snippet[: max(0, budget - used)]
        used += len(snippet)
        parts.append(f"[{match['file_name']}] {snippet}")
        sources.append({
            "file_id": match["file_id"],
            "file_name": match["file_name"],
            "collection_id": match["collection_id"],
            "collection_name": match["collection_name"],
            "similarity": match["similarity"],
            "chunk_index": match["chunk_index"],
        })

    return {
        "content": "\n\n".join(parts),
        "sources": sources,
    }
