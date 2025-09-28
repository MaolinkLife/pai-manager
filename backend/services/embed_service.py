# ==========================================================
# Module: embed_service.py (refactored)
# Purpose: Manage text embeddings via Ollama (primary) or
#          SentenceTransformers (fallback)
# Used by: RAG and memory services
#
# Key improvements:
# - Корректный вызов Ollama /api/embeddings (prompt, не input)
# - Нормальный логгер вместо print + структурные исключения
# - Чёткая карта алиасов Ollama -> валидные ST модели
# - Кэширование ST-моделей + thread-safe загрузка
# - Единый API для single/batch: get_embedding(s)
# - Ретраи к Ollama (конфигурируемые)
# - Жёсткая типизация, докстринги, явные таймауты
# ==========================================================

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

import requests
from requests import Response

from sentence_transformers import SentenceTransformer

# ---------------------------
# Logging
# ---------------------------

_LOG_LEVEL = os.getenv("EMBED_SVC_LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=_LOG_LEVEL, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("embed_service")

# ---------------------------
# Config
# ---------------------------

# Ollama
OLLAMA_URL: str = os.getenv("OLLAMA_EMBED_URL", "http://localhost:11434/api/embeddings")
OLLAMA_DEFAULT_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_TIMEOUT_SEC: float = float(os.getenv("OLLAMA_TIMEOUT_SEC", "30"))
OLLAMA_MAX_RETRIES: int = int(os.getenv("OLLAMA_MAX_RETRIES", "2"))
OLLAMA_RETRY_BACKOFF_SEC: float = float(os.getenv("OLLAMA_RETRY_BACKOFF_SEC", "0.75"))

# SentenceTransformers
DEFAULT_ST_MODEL_NAME: str = os.getenv(
    "ST_DEFAULT_MODEL", "paraphrase-multilingual-MiniLM-L12-v2"
)

# Алиасы имён Ollama → валидные имена ST
# (Если Ollama-модель недоступна, сюда маппим на локальную ST-модель.)
OLLAMA_TO_ST_FALLBACK: Dict[str, str] = {
    "nomic-embed-text": DEFAULT_ST_MODEL_NAME,
}

# Если явно хотят Nomic в ST — указывайте полное имя репозитория HF.
# Пример: "nomic-ai/nomic-embed-text-v1.5"
# Для nomic-ai в ST часто требуется trust_remote_code=True.
TRUST_REMOTE_CODE_ORGS: Tuple[str, ...] = ("nomic-ai/",)

# ---------------------------
# Errors
# ---------------------------


class EmbeddingError(Exception):
    """Base embedding error."""


class OllamaError(EmbeddingError):
    """Raised for Ollama-specific failures."""


class STModelError(EmbeddingError):
    """Raised for SentenceTransformers-specific failures."""


# ---------------------------
# Internal ST model cache
# ---------------------------

_st_model_lock = Lock()
_st_models_cache: Dict[str, SentenceTransformer] = {}


def _should_trust_remote_code(model_name: str) -> bool:
    """Нужно ли включать trust_remote_code для данного имени модели."""
    return any(model_name.startswith(org) for org in TRUST_REMOTE_CODE_ORGS)


def _normalize_st_model_name(name: Optional[str]) -> str:
    """
    Нормализует имя ST-модели:
    - Если None → DEFAULT_ST_MODEL_NAME
    - Если без слеша (вероятно алиас Ollama) → маппим через OLLAMA_TO_ST_FALLBACK
    - Иначе возвращаем как есть (считаем HF-ID валидным)
    """
    if not name:
        return DEFAULT_ST_MODEL_NAME
    if "/" not in name:
        return OLLAMA_TO_ST_FALLBACK.get(name, DEFAULT_ST_MODEL_NAME)
    return name


def _load_st_model(model_name: str) -> Optional[SentenceTransformer]:
    """
    Загружает ST-модель с учётом trust_remote_code для некоторых org.
    Возвращает None при ошибке (логирует причину).
    """
    try:
        trust = _should_trust_remote_code(model_name)
        model = SentenceTransformer(model_name, trust_remote_code=trust)
        return model
    except Exception as exc:
        logger.error("ST model load failed [%s]: %s", model_name, exc)
        return None


def _get_st_model(model_name: Optional[str] = None) -> Optional[SentenceTransformer]:
    """
    Достаёт (или лениво загружает и кеширует) ST-модель.
    Возвращает None, если загрузить не удалось.
    """
    name = _normalize_st_model_name(model_name)

    with _st_model_lock:
        cached = _st_models_cache.get(name)
        if cached is not None:
            return cached

        model = _load_st_model(name)
        if model is not None:
            _st_models_cache[name] = model
        return model


# ---------------------------
# HTTP helpers
# ---------------------------


def _safe_read_text(res: Optional[Response]) -> str:
    try:
        return res.text if res is not None else ""
    except Exception:
        return ""


def _post_with_retries(
    url: str, json_payload: dict, timeout: float, max_retries: int, backoff: float
) -> Response:
    """
    Выполняет POST с ретраями по сетевым/HTTP ошибкам (5xx).
    4xx считаем фатальными сразу.
    """
    last_exc: Optional[Exception] = None
    res: Optional[Response] = None

    for attempt in range(max_retries + 1):
        try:
            res = requests.post(url, json=json_payload, timeout=timeout)
            # 2xx — ок
            if 200 <= res.status_code < 300:
                return res
            # 4xx — фатально
            if 400 <= res.status_code < 500:
                raise OllamaError(
                    f"Ollama HTTP {res.status_code}: {res.reason} | body={_safe_read_text(res)[:400]}"
                )
            # 5xx — можно ретраить
            last_exc = OllamaError(
                f"Ollama HTTP {res.status_code}: {res.reason} | body={_safe_read_text(res)[:400]}"
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_exc = exc

        if attempt < max_retries:
            sleep_for = backoff * (2**attempt)
            time.sleep(sleep_for)

    assert last_exc is not None
    raise OllamaError(f"Ollama request failed after retries: {last_exc}")


# ---------------------------
# Core: Ollama embeddings
# ---------------------------


def _ollama_embed_one(text: str, model: str) -> Optional[List[float]]:
    """
    Делает один запрос эмбеддинга в Ollama.
    Возвращает вектор или None, если embedding пустой.
    Исключения пробрасывает наверх как OllamaError.
    """
    payload = {
        "model": model,
        "prompt": text,  # ВАЖНО: у Ollama ключ prompt, не input
    }
    res = _post_with_retries(
        url=OLLAMA_URL,
        json_payload=payload,
        timeout=OLLAMA_TIMEOUT_SEC,
        max_retries=OLLAMA_MAX_RETRIES,
        backoff=OLLAMA_RETRY_BACKOFF_SEC,
    )

    try:
        data = res.json()
    except json.JSONDecodeError as exc:
        raise OllamaError(
            f"Invalid JSON from Ollama: {exc} | body={_safe_read_text(res)[:400]}"
        ) from exc

    emb = data.get("embedding")
    if not emb:
        # возвращаем None, чтобы допустим fallback сработал
        logger.warning("Ollama returned empty embedding for model=%s", model)
        return None
    if not isinstance(emb, list):
        raise OllamaError(
            f"Unexpected embedding type from Ollama: {type(emb).__name__}"
        )
    return emb


def get_embedding_ollama(
    text: str,
    model: str = OLLAMA_DEFAULT_MODEL,
    strict: bool = False,
) -> Optional[List[float]]:
    """
    Получить эмбеддинг через Ollama для одного текста.
    strict=False: вернуть None на пустой/проблемный ответ.
    strict=True: бросать исключения при любой аномалии.
    """
    try:
        return _ollama_embed_one(text, model)
    except OllamaError as exc:
        if strict:
            raise
        logger.error("Ollama embedding error [%s]: %s", model, exc)
        return None


def get_embeddings_ollama(
    texts: Sequence[str],
    model: str = OLLAMA_DEFAULT_MODEL,
    strict: bool = False,
) -> List[Optional[List[float]]]:
    """
    Батч через простую последовательную отправку (Ollama embeddings — по одному prompt):
    Возвращает список в длину texts, элементы — вектор или None (если strict=False).
    """
    results: List[Optional[List[float]]] = []
    for t in texts:
        results.append(get_embedding_ollama(t, model=model, strict=strict))
    return results


# ---------------------------
# Core: SentenceTransformers embeddings
# ---------------------------


def _st_embed(
    texts: Sequence[str],
    model_name: Optional[str] = None,
) -> Optional[List[List[float]]]:
    """
    Возвращает батч эмбеддингов через ST. None — если модель не загрузилась.
    Исключения логируются и преобразуются в None (семантика — мягкий фолбэк).
    """
    st_model = _get_st_model(model_name)
    if st_model is None:
        logger.error(
            "ST model is unavailable (requested=%s)",
            model_name or DEFAULT_ST_MODEL_NAME,
        )
        return None

    try:
        # SentenceTransformers сам умеет батчить
        vecs = st_model.encode(list(texts))  # numpy array
        # Преобразуем в чистые list[list[float]]
        return [v.tolist() for v in vecs]
    except Exception as exc:
        logger.error(
            "ST embedding error [%s]: %s",
            getattr(st_model, "model_card", None)
            or (model_name or DEFAULT_ST_MODEL_NAME),
            exc,
        )
        return None


def get_embedding_st(
    text: str,
    model: Optional[str] = None,
) -> Optional[List[float]]:
    """Эмбеддинг одного текста через ST (None при ошибке/недоступности)."""
    batch = _st_embed([text], model_name=model)
    return batch[0] if batch else None


def get_embeddings_st(
    texts: Sequence[str],
    model: Optional[str] = None,
) -> List[Optional[List[float]]]:
    """
    Батч эмбеддингов через ST.
    Возвращает список длиной texts; если ST недоступен, список из None.
    """
    batch = _st_embed(texts, model_name=model)
    if batch is None:
        return [None for _ in texts]
    return batch


# ---------------------------
# Unified API
# ---------------------------


@dataclass(frozen=True)
class Provider:
    OLLAMA: str = "ollama"
    ST: str = "st"
    AUTO: str = "auto"


def _as_text_list(text_or_texts: Union[str, Sequence[str]]) -> List[str]:
    if isinstance(text_or_texts, str):
        return [text_or_texts]
    return list(text_or_texts)


def get_embedding(
    text: str,
    provider: str = Provider.AUTO,
    model: str = OLLAMA_DEFAULT_MODEL,
) -> Optional[List[float]]:
    """
    Unified single-text helper.

    provider:
      - "ollama" → только Ollama
      - "st"     → только SentenceTransformers
      - "auto"   → сначала Ollama, при неудаче — ST (с алиасами)
    """
    p = (provider or Provider.AUTO).lower()

    if p == Provider.OLLAMA:
        return get_embedding_ollama(text, model=model)

    if p == Provider.ST:
        return get_embedding_st(text, model=model)

    if p == Provider.AUTO:
        vec = get_embedding_ollama(text, model=model)
        return vec if vec is not None else get_embedding_st(text, model=model)

    raise ValueError(f"Unknown provider: {provider}")


def get_embeddings(
    texts: Union[str, Sequence[str]],
    provider: str = Provider.AUTO,
    model: str = OLLAMA_DEFAULT_MODEL,
) -> List[Optional[List[float]]]:
    """
    Unified batch helper.
    Возвращает список той же длины, что и входной батч.

    Семантика AUTO:
      1) Пытаемся получить эмбеддинги через Ollama (по одному prompt).
      2) Если какой-то элемент вернулся None — пробуем добить его через ST.
    """
    p = (provider or Provider.AUTO).lower()
    items = _as_text_list(texts)

    if p == Provider.OLLAMA:
        return get_embeddings_ollama(items, model=model)

    if p == Provider.ST:
        return get_embeddings_st(items, model=model)

    if p == Provider.AUTO:
        # шаг 1: Ollama
        res = get_embeddings_ollama(items, model=model)
        # шаг 2: для None — ST
        need_fallback_indices = [i for i, v in enumerate(res) if v is None]
        if not need_fallback_indices:
            return res

        # Собираем только тексты, которые не удалось получить у Ollama
        fallback_inputs = [items[i] for i in need_fallback_indices]
        fallback_vecs = get_embeddings_st(fallback_inputs, model=model)

        # Мерджим результаты
        it = iter(fallback_vecs)
        for i in need_fallback_indices:
            res[i] = next(it, None)
        return res

    raise ValueError(f"Unknown provider: {provider}")


# ---------------------------
# Dual Collection Support
# ---------------------------


def get_both_embeddings(
    text: str,
) -> tuple[Optional[List[float]], Optional[List[float]]]:
    """
    Получает оба эмбеддинга сразу: 384-dim (ST) и 768-dim (Ollama)
    Возвращает tuple: (embedding_384, embedding_768)
    """
    embedding_384 = get_embedding_st(text)
    embedding_768 = get_embedding_ollama(text)

    return embedding_384, embedding_768


def get_embeddings_batch_both(
    texts: Sequence[str],
) -> tuple[List[Optional[List[float]]], List[Optional[List[float]]]]:
    """
    Получает батч обоих эмбеддингов
    Возвращает tuple: (embeddings_384, embeddings_768)
    """
    embeddings_384 = get_embeddings_st(texts)
    embeddings_768 = get_embeddings_ollama(texts)

    return embeddings_384, embeddings_768
