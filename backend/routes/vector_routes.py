from fastapi import APIRouter, Query
from services import embed_service, vector_service

router = APIRouter(prefix="/api/vector", tags=["vector"])

@router.post("/add")
def add_text(q: str = Query(..., description="Текст для добавления")):
    emb = embed_service.get_embedding(q, provider="auto")
    vector_service.add_texts([q], [emb])
    return {"added": q, "length": len(emb)}

@router.get("/search")
def search_text(q: str = Query(..., description="Поисковый запрос")):
    query_emb = embed_service.get_embedding(q, provider="auto")
    results = vector_service.search(query_emb, top_k=3)
    return results
