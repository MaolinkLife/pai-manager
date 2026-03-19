# ==========================================================
# Module: vector_service.py
# Purpose: Manage vector DB (Chroma) for semantic memory
# ==========================================================

import os
import uuid
import chromadb
from chromadb.config import Settings
from constants.paths import STORAGE_DIR

os.environ.setdefault("ANONYMIZED_TELEMETRY", "FALSE")


CHROMA_DIR = os.path.join(STORAGE_DIR, "vector_store")
LEGACY_CHROMA_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "storage", "vector_store")
)


def _ensure_vector_dir() -> None:
    os.makedirs(CHROMA_DIR, exist_ok=True)


def _migrate_legacy_root_store() -> None:
    """
    Move legacy root-level storage/vector_store/chroma.sqlite3 to backend/storage/vector_store
    if backend target file is missing.
    """
    legacy_file = os.path.join(LEGACY_CHROMA_DIR, "chroma.sqlite3")
    target_file = os.path.join(CHROMA_DIR, "chroma.sqlite3")
    if not os.path.isfile(legacy_file):
        return
    if os.path.isfile(target_file):
        return
    try:
        os.replace(legacy_file, target_file)
    except Exception:
        # Non-critical migration path; runtime can continue with existing target.
        pass


_ensure_vector_dir()
_migrate_legacy_root_store()

_client = chromadb.PersistentClient(
    path=CHROMA_DIR,
    settings=Settings(
        anonymized_telemetry=False,
    ),
)


def _get_collection(name: str = "pai_memory"):
    return _client.get_or_create_collection(
        name=name, metadata={"hnsw:space": "cosine"}
    )


def add_texts(
    texts,
    embeddings,
    metadatas=None,
    ids=None,
    collection_name: str = "pai_memory",
):
    collection = _get_collection(collection_name)

    if metadatas is None:
        metadatas = [{"source": "manual"} for _ in texts]

    if ids is None:
        ids = [f"doc_{uuid.uuid4()}" for _ in texts]

    collection.add(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )


def upsert_text(
    doc_id: str,
    text: str,
    embedding,
    metadata: dict | None = None,
    collection_name: str = "pai_memory",
):
    collection = _get_collection(collection_name)
    collection.upsert(
        ids=[doc_id],
        documents=[text],
        embeddings=[embedding],
        metadatas=[metadata or {}],
    )


def delete_text(doc_id: str, collection_name: str = "pai_memory"):
    collection = _get_collection(collection_name)
    collection.delete(ids=[doc_id])


def search(query_embedding, top_k=3, collection_name: str = "pai_memory"):
    """Find the nearest documents by embedding."""
    collection = _get_collection(collection_name)
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"],
    )
    return results


def reset(collection_name: str = "pai_memory"):
    """Полностью очистить коллекцию и пересоздать с cosine similarity."""
    _client.delete_collection(collection_name)
    _get_collection(collection_name)
