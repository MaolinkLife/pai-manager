# ==========================================================
# Module: vector_service.py
# Purpose: Manage vector DB (Chroma) for semantic memory
# ==========================================================

import chromadb
from chromadb.config import Settings

CHROMA_DIR = "./storage/vector_store"

_client = chromadb.PersistentClient(path=CHROMA_DIR)
_collection = _client.get_or_create_collection(
    name="pai_memory",
    metadata={"hnsw:space": "cosine"}
)

# Use cosine similarity instead of L2 distance
_collection = _client.get_or_create_collection(
    name="pai_memory",
    metadata={"hnsw:space": "cosine"}
)

def add_texts(texts, embeddings, metadatas=None):
    ids = [f"doc_{i}" for i in range(len(texts))]
    if metadatas is None:
        metadatas = [{"source": "manual"} for _ in texts]

    _collection.add(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas
    )

def search(query_embedding, top_k=3):
    """Find the nearest documents by embedding."""
    results = _collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas", "distances"]
    )
    return results

def reset():
    """
    Полностью очистить коллекцию и пересоздать с cosine similarity
    """
    global _collection
    _client.delete_collection("pai_memory")
    _collection = _client.get_or_create_collection(
        name="pai_memory",
        metadata={"hnsw:space": "cosine"}
    )
