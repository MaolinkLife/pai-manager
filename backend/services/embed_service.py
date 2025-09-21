# ==========================================================
# Module: embed_service.py
# Purpose: Manage embeddings (Ollama or local ST model)
# Used: by RAG and memory services
# Features:
# - Generate embeddings via Ollama API
# - Generate embeddings via SentenceTransformers (fallback)
# - Unified entrypoint get_embedding()
# ==========================================================

import requests
from sentence_transformers import SentenceTransformer

# Ollama API endpoint
OLLAMA_URL = "http://localhost:11434/api/embeddings"

# Load local model for fallback
_st_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

def get_embedding_ollama(text: str, model: str = "nomic-embed-text"):
    """Retrieve an embedding via Ollama."""
    try:
        payload = {
            "model": model,
            "input": [text]
        }
        res = requests.post(OLLAMA_URL, json=payload)
        data = res.json()
        emb = data.get("embedding", [])
        return emb if emb else None
    except Exception as e:
        print(f"[Ollama Embedding Error]: {e}")
        return None

def get_embedding_st(text: str):
    """Retrieve an embedding locally via SentenceTransformers."""
    try:
        vec = _st_model.encode([text])
        return vec[0].tolist()
    except Exception as e:
        print(f"[ST Embedding Error]: {e}")
        return None

def get_embedding(text: str, provider: str = "auto", model: str = "nomic-embed-text"):
    """
    Unified helper:
    - provider="ollama" → use Ollama only
    - provider="st" → use SentenceTransformers only
    - provider="auto" → try Ollama first, then fall back to ST
    """
    if provider == "ollama":
        return get_embedding_ollama(text, model)
    elif provider == "st":
        return get_embedding_st(text)
    elif provider == "auto":
        emb = get_embedding_ollama(text, model)
        return emb if emb else get_embedding_st(text)
    else:
        raise ValueError(f"Unknown provider: {provider}")
