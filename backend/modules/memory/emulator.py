"""Manual memory search emulator using the same layered retrieval idea as runtime memory."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from models.models import History
from modules.memory.embeddings import get_embedding, get_embeddings
from modules.memory.knowledge import (
    ensure_memory_knowledge_schema,
    expand_associative_terms,
    search_anchors,
)
from modules.memory.short_term import ShortTermRecord, load_recent_records
from services import character_service, database_service
from services import config_service
from services.db_core import SessionLocal
from modules.system.service import get_active_character_name

DEFAULT_RECENT_PAIRS = 32
DEFAULT_WINDOW_PAIRS = 32
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_TOP_K = 8
DEFAULT_KEYWORD_MIN_OVERLAP = 0.25
DEFAULT_KEYWORD_MIN_SCORE = 0.15
DEFAULT_VECTOR_THRESHOLD = 0.7
DEFAULT_STOPWORDS = {
    "это",
    "как",
    "или",
    "если",
    "что",
    "and",
    "the",
    "with",
}


@dataclass
class VectorProfile:
    name: str
    provider: str
    model: str
    threshold: float
    enabled: bool


def _safe_lower(value: Any) -> str:
    return str(value or "").strip().lower()


def _normalize_utc_iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    raw = value.isoformat() if hasattr(value, "isoformat") else str(value)
    if not raw:
        return None
    if raw.endswith("Z") or "+" in raw[10:] or "-" in raw[10:]:
        return raw
    if "T" in raw:
        return f"{raw}Z"
    return raw


def _tokenize(text: str, stopwords: Optional[set[str]] = None) -> List[str]:
    tokens = [token for token in re.findall(r"[\w-]{2,}", text.lower()) if len(token) > 2]
    if stopwords:
        lowered = {s.lower() for s in stopwords}
        tokens = [token for token in tokens if token not in lowered]
    return tokens


def _keyword_score(
    query_tokens: Sequence[str],
    payload_tokens: Sequence[str],
    *,
    min_overlap: float = DEFAULT_KEYWORD_MIN_OVERLAP,
) -> Tuple[float, float]:
    if not query_tokens or not payload_tokens:
        return 0.0, 0.0

    payload_set = set(payload_tokens)
    overlap_tokens = [token for token in query_tokens if token in payload_set]
    if not overlap_tokens:
        return 0.0, 0.0

    overlap_ratio = len(overlap_tokens) / max(len(query_tokens), 1)
    coverage_ratio = len(overlap_tokens) / max(len(payload_tokens), 1)
    if overlap_ratio < min_overlap:
        return 0.0, overlap_ratio
    score = (overlap_ratio * 0.7) + (coverage_ratio * 0.3)
    return score, overlap_ratio


def _normalize_for_match(text: str) -> str:
    return " ".join(re.findall(r"[\w-]+", (text or "").lower()))


def _contains_exact_phrase(text: str, phrase: str) -> bool:
    normalized_text = _normalize_for_match(text)
    normalized_phrase = _normalize_for_match(phrase)
    if not normalized_text or not normalized_phrase:
        return False
    return normalized_phrase in normalized_text


def _exact_token_hits(query_tokens: Sequence[str], text: str) -> int:
    if not query_tokens:
        return 0
    normalized_text = _normalize_for_match(text)
    token_set = set(normalized_text.split())
    return sum(1 for token in query_tokens if token in token_set)


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = sum(a * a for a in vec_a) ** 0.5
    mag_b = sum(b * b for b in vec_b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _to_payload(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": item.get("id"),
        "role": item.get("role", "assistant"),
        "content": item.get("content", ""),
        "timestamp": item.get("timestamp"),
        "tags": item.get("tags") or [],
    }


class MemorySearchEmulator:
    def emulate(
        self,
        *,
        query: str,
        message_id: Optional[str] = None,
        recent_pairs: int = DEFAULT_RECENT_PAIRS,
        window_pairs: int = DEFAULT_WINDOW_PAIRS,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        top_k: int = DEFAULT_TOP_K,
    ) -> Dict[str, Any]:
        query = (query or "").strip()
        message_id = (message_id or "").strip()

        char_name = get_active_character_name(default="default_waifu")
        character = character_service.get_or_create_character(char_name)
        ensure_memory_knowledge_schema()

        profiles = self._load_vector_profiles()
        query_tokens = _tokenize(query, DEFAULT_STOPWORDS)
        query_vectors = self._compute_query_vectors(query, profiles)

        stages: List[Dict[str, Any]] = []
        trace_hits: List[Dict[str, Any]] = []

        # Stage 1: recent window
        recent_limit = max(1, int(recent_pairs)) * 2
        recent_rows = database_service.get_history(char_name, limit=recent_limit) or []
        recent_payloads = [_to_payload(row) for row in reversed(recent_rows)]
        stage_1_hits = self._rank_messages(
            recent_payloads,
            query=query,
            message_id=message_id,
            query_tokens=query_tokens,
            profiles=profiles,
            query_vectors=query_vectors,
            top_k=top_k,
            allow_vector_only=False,
        )
        stages.append(
            {
                "stage": "recent_window",
                "label": "Recent window",
                "status": "hit" if stage_1_hits else "miss",
                "scanned": len(recent_payloads),
                "hits": len(stage_1_hits),
            }
        )
        trace_hits.extend(stage_1_hits)

        # Stage 2: current session by windows (today)
        if not stage_1_hits:
            session_payloads = self._load_today_session_messages(character.id)
            window_size = max(1, int(window_pairs)) * 2
            session_hits: List[Dict[str, Any]] = []
            for idx in range(0, len(session_payloads), window_size):
                window = session_payloads[idx : idx + window_size]
                window_hits = self._rank_messages(
                    window,
                    query=query,
                    message_id=message_id,
                    query_tokens=query_tokens,
                    profiles=profiles,
                    query_vectors=query_vectors,
                    top_k=top_k,
                    allow_vector_only=False,
                )
                if window_hits:
                    session_hits.extend(window_hits)
                    break
            stages.append(
                {
                    "stage": "session_today",
                    "label": "Current session",
                    "status": "hit" if session_hits else "miss",
                    "scanned": len(session_payloads),
                    "hits": len(session_hits),
                }
            )
            trace_hits.extend(session_hits)

        # Stage 3: recent days summaries -> resolve day messages by windows
        if not trace_hits:
            records = load_recent_records(days=max(1, int(lookback_days)))
            day_hits: List[Dict[str, Any]] = []
            matched_records = self._rank_short_term_records(
                records=records,
                query=query,
                query_tokens=query_tokens,
                profiles=profiles,
                query_vectors=query_vectors,
                top_k=max(3, top_k),
                allow_vector_only=False,
            )
            for record in matched_records:
                day_payloads = self._load_day_messages(character.id, record["day_start"])
                window_size = max(1, int(window_pairs)) * 2
                for idx in range(0, len(day_payloads), window_size):
                    window = day_payloads[idx : idx + window_size]
                    window_hits = self._rank_messages(
                        window,
                        query=query,
                        message_id=message_id,
                        query_tokens=query_tokens,
                        profiles=profiles,
                        query_vectors=query_vectors,
                        top_k=top_k,
                        allow_vector_only=False,
                    )
                    if window_hits:
                        for hit in window_hits:
                            hit["from_short_term_record"] = record["id"]
                            hit["from_short_term_day"] = record["day"]
                        day_hits.extend(window_hits)
                        break
                if day_hits:
                    break

            stages.append(
                {
                    "stage": "daily_summaries",
                    "label": "Recent daily summaries",
                    "status": "hit" if day_hits else "miss",
                    "scanned": len(records),
                    "hits": len(day_hits),
                }
            )
            trace_hits.extend(day_hits)

        # Stage 4: global anchors
        if not trace_hits:
            date_keys = self._derive_date_keys(query)
            anchor_hits = search_anchors(
                character_id=character.id,
                query_tokens=query_tokens,
                date_keys=date_keys,
                limit=max(5, top_k),
            )
            stages.append(
                {
                    "stage": "global_anchors",
                    "label": "Global anchors",
                    "status": "hit" if anchor_hits else "miss",
                    "scanned": len(anchor_hits),
                    "hits": len(anchor_hits),
                }
            )

            for anchor in anchor_hits:
                refs = anchor.get("refs") or {}
                day_hits: List[Dict[str, Any]] = []
                message_ids = refs.get("message_ids") if isinstance(refs, dict) else []
                day_refs = refs.get("days") if isinstance(refs, dict) else []

                if isinstance(message_ids, list) and message_ids:
                    message_payloads = self._load_messages_by_ids(character.id, message_ids)
                    message_hits = self._rank_messages(
                        message_payloads,
                        query=query,
                        message_id=message_id,
                        query_tokens=query_tokens,
                        profiles=profiles,
                        query_vectors=query_vectors,
                        top_k=top_k,
                        allow_vector_only=False,
                    )
                    day_hits.extend(message_hits)

                if not day_hits and isinstance(day_refs, list):
                    for day_ref in day_refs[:3]:
                        day_payloads = self._load_day_messages_by_date(character.id, str(day_ref))
                        if not day_payloads:
                            continue
                        window_hits = self._rank_messages(
                            day_payloads,
                            query=query,
                            message_id=message_id,
                            query_tokens=query_tokens,
                            profiles=profiles,
                            query_vectors=query_vectors,
                            top_k=top_k,
                            allow_vector_only=False,
                        )
                        if window_hits:
                            day_hits.extend(window_hits)
                            break

                if day_hits:
                    for hit in day_hits:
                        hit["from_anchor"] = anchor.get("anchor_key")
                    trace_hits.extend(day_hits)
                    break

        # Stage 5: associative expansion
        if not trace_hits:
            expansions = expand_associative_terms(
                character_id=character.id,
                tokens=query_tokens,
                limit=max(4, top_k),
            )
            expanded_query = query
            if expansions:
                extra_terms = [str(item.get("term") or "").strip() for item in expansions]
                extra_terms = [term for term in extra_terms if term]
                if extra_terms:
                    expanded_query = " ".join([query] + extra_terms)

            assoc_query_tokens = _tokenize(expanded_query, DEFAULT_STOPWORDS)
            assoc_query_vectors = self._compute_query_vectors(expanded_query, profiles)
            assoc_rows = database_service.get_history(
                char_name, limit=max(1, int(recent_pairs)) * 2
            ) or []
            assoc_payloads = [_to_payload(row) for row in reversed(assoc_rows)]
            assoc_hits = self._rank_messages(
                assoc_payloads,
                query=expanded_query,
                message_id=message_id,
                query_tokens=assoc_query_tokens,
                profiles=profiles,
                query_vectors=assoc_query_vectors,
                top_k=top_k,
                allow_vector_only=True,
            )
            for hit in assoc_hits:
                hit["expanded_query"] = expanded_query
                hit["expanded_terms"] = expansions

            stages.append(
                {
                    "stage": "associative_graph",
                    "label": "Associative graph",
                    "status": "hit" if assoc_hits else "miss",
                    "scanned": len(assoc_payloads),
                    "hits": len(assoc_hits),
                }
            )
            trace_hits.extend(assoc_hits)

        trace_hits.sort(key=lambda item: float(item.get("score") or 0.0), reverse=True)
        result_hits = trace_hits[: max(1, top_k)]

        return {
            "status": "success",
            "query": query,
            "message_id": message_id or None,
            "character": {"id": character.id, "name": character.name},
            "settings": {
                "recent_pairs": recent_pairs,
                "window_pairs": window_pairs,
                "lookback_days": lookback_days,
                "top_k": top_k,
                "profiles": [
                    {
                        "name": p.name,
                        "provider": p.provider,
                        "model": p.model,
                        "threshold": p.threshold,
                    }
                    for p in profiles
                ],
            },
            "trace": stages,
            "hits": result_hits,
        }

    def _load_vector_profiles(self) -> List[VectorProfile]:
        retrieval_cfg = config_service.get_config_value("rag.retrieval", {}) or {}
        vectors_cfg = retrieval_cfg.get("vectors", {}) if isinstance(retrieval_cfg, dict) else {}
        profiles_cfg = vectors_cfg.get("profiles", {}) if isinstance(vectors_cfg, dict) else {}

        profiles: List[VectorProfile] = []
        if isinstance(profiles_cfg, dict):
            for name, cfg in profiles_cfg.items():
                if not isinstance(cfg, dict):
                    continue
                enabled = bool(cfg.get("enabled", True))
                if not enabled:
                    continue
                profiles.append(
                    VectorProfile(
                        name=name,
                        provider=str(cfg.get("provider") or config_service.get_config_value("memory.embedding_provider", "auto")),
                        model=str(cfg.get("model") or config_service.get_config_value("memory.embedding_model", "nomic-embed-text")),
                        threshold=float(cfg.get("threshold", DEFAULT_VECTOR_THRESHOLD)),
                        enabled=enabled,
                    )
                )

        if profiles:
            return profiles

        return [
            VectorProfile(
                name="default",
                provider=str(config_service.get_config_value("memory.embedding_provider", "auto")),
                model=str(config_service.get_config_value("memory.embedding_model", "nomic-embed-text")),
                threshold=float(config_service.get_config_value("memory.similarity_threshold", DEFAULT_VECTOR_THRESHOLD)),
                enabled=True,
            )
        ]

    def _compute_query_vectors(
        self,
        query: str,
        profiles: Sequence[VectorProfile],
    ) -> Dict[str, Optional[List[float]]]:
        vectors: Dict[str, Optional[List[float]]] = {}
        for profile in profiles:
            vectors[profile.name] = get_embedding(
                query,
                provider=profile.provider,
                model=profile.model,
                settings={"name": profile.name},
                profile=profile.name,
            )
        return vectors

    def _rank_messages(
        self,
        payloads: Sequence[Dict[str, Any]],
        *,
        query: str,
        message_id: str,
        query_tokens: Sequence[str],
        profiles: Sequence[VectorProfile],
        query_vectors: Dict[str, Optional[List[float]]],
        top_k: int,
        allow_vector_only: bool = True,
    ) -> List[Dict[str, Any]]:
        if not payloads:
            return []

        texts = [str(item.get("content") or "") for item in payloads]
        vector_hits: Dict[str, Dict[str, float]] = {}

        for profile in profiles:
            query_vec = query_vectors.get(profile.name)
            if query_vec is None:
                continue
            embeddings = get_embeddings(
                texts,
                provider=profile.provider,
                model=profile.model,
                settings={"name": profile.name},
                profile=profile.name,
            )
            for item, emb in zip(payloads, embeddings):
                if emb is None:
                    continue
                similarity = _cosine_similarity(query_vec, emb)
                if similarity < profile.threshold:
                    continue
                item_id = str(item.get("id") or "")
                bucket = vector_hits.setdefault(item_id, {})
                bucket[profile.name] = similarity

        ranked: List[Dict[str, Any]] = []
        for item in payloads:
            item_id = str(item.get("id") or "")
            text = str(item.get("content") or "")
            payload_tokens = _tokenize(text, DEFAULT_STOPWORDS)
            keyword_value, overlap = _keyword_score(query_tokens, payload_tokens)
            vector_scores = vector_hits.get(item_id, {})
            vector_value = max(vector_scores.values()) if vector_scores else 0.0
            exact_phrase_hit = _contains_exact_phrase(text, query) if query else False
            token_hits = _exact_token_hits(query_tokens, text)

            message_id_hit = 1.0 if message_id and message_id == item_id else 0.0
            if query:
                if (
                    keyword_value < DEFAULT_KEYWORD_MIN_SCORE
                    and vector_value <= 0
                    and message_id_hit <= 0
                    and not exact_phrase_hit
                    and token_hits <= 0
                ):
                    continue
            elif message_id:
                if message_id_hit <= 0:
                    continue
            else:
                continue

            # Lexical-first for short calibration queries (1-2 tokens).
            short_query = len(query_tokens) <= 2
            if short_query:
                vector_weight = 0.35
                keyword_weight = 0.65
            else:
                vector_weight = 0.70
                keyword_weight = 0.30

            exact_boost = 0.45 if exact_phrase_hit else 0.0
            token_boost = 0.0
            if query_tokens:
                token_boost = min(token_hits / len(query_tokens), 1.0) * 0.35

            score = (
                (vector_value * vector_weight)
                + (keyword_value * keyword_weight)
                + exact_boost
                + token_boost
                + (message_id_hit * 2.5)
            )

            has_lexical_signal = bool(
                exact_phrase_hit
                or token_hits > 0
                or keyword_value >= DEFAULT_KEYWORD_MIN_SCORE
                or message_id_hit > 0
            )
            if short_query and not allow_vector_only and not has_lexical_signal:
                continue

            ranked.append(
                {
                    "id": item_id,
                    "role": item.get("role"),
                    "content": text,
                    "timestamp": item.get("timestamp"),
                    "score": round(score, 4),
                    "details": {
                        "vector_scores": {k: round(v, 4) for k, v in vector_scores.items()},
                        "keyword_score": round(keyword_value, 4),
                        "keyword_overlap": round(overlap, 4),
                        "exact_phrase_hit": exact_phrase_hit,
                        "exact_token_hits": token_hits,
                        "message_id_hit": bool(message_id_hit),
                    },
                }
            )

        ranked.sort(key=lambda entry: float(entry.get("score") or 0.0), reverse=True)
        return ranked[: max(1, top_k)]

    def _rank_short_term_records(
        self,
        *,
        records: Sequence[ShortTermRecord],
        query: str,
        query_tokens: Sequence[str],
        profiles: Sequence[VectorProfile],
        query_vectors: Dict[str, Optional[List[float]]],
        top_k: int,
        allow_vector_only: bool = True,
    ) -> List[Dict[str, Any]]:
        if not records:
            return []

        combined_texts = [
            f"{record.summary}\n{' '.join(record.themes or [])}".strip()
            for record in records
        ]
        vector_hits: Dict[str, Dict[str, float]] = {}

        for profile in profiles:
            query_vec = query_vectors.get(profile.name)
            if query_vec is None:
                continue
            embeddings = get_embeddings(
                combined_texts,
                provider=profile.provider,
                model=profile.model,
                settings={"name": profile.name},
                profile=profile.name,
            )
            for record, emb in zip(records, embeddings):
                if emb is None:
                    continue
                similarity = _cosine_similarity(query_vec, emb)
                if similarity < profile.threshold:
                    continue
                bucket = vector_hits.setdefault(record.id, {})
                bucket[profile.name] = similarity

        ranked: List[Dict[str, Any]] = []
        for record in records:
            text = f"{record.summary}\n{' '.join(record.themes or [])}"
            payload_tokens = _tokenize(text, DEFAULT_STOPWORDS)
            keyword_value, overlap = _keyword_score(query_tokens, payload_tokens)
            vector_scores = vector_hits.get(record.id, {})
            vector_value = max(vector_scores.values()) if vector_scores else 0.0
            exact_phrase_hit = _contains_exact_phrase(text, query) if query else False
            token_hits = _exact_token_hits(query_tokens, text)
            if query and keyword_value < DEFAULT_KEYWORD_MIN_SCORE and vector_value <= 0:
                continue

            score = (vector_value * 0.7) + (keyword_value * 0.3)
            short_query = len(query_tokens) <= 2
            has_lexical_signal = bool(
                exact_phrase_hit or token_hits > 0 or keyword_value >= DEFAULT_KEYWORD_MIN_SCORE
            )
            if short_query and not allow_vector_only and not has_lexical_signal:
                continue

            day_start = record.created_at
            if day_start.tzinfo is None:
                day_start = day_start.replace(tzinfo=timezone.utc)
            ranked.append(
                {
                    "id": record.id,
                    "day": day_start.date().isoformat(),
                    "day_start": day_start,
                    "score": round(score, 4),
                    "details": {
                        "vector_scores": {k: round(v, 4) for k, v in vector_scores.items()},
                        "keyword_score": round(keyword_value, 4),
                        "keyword_overlap": round(overlap, 4),
                        "exact_phrase_hit": exact_phrase_hit,
                        "exact_token_hits": token_hits,
                    },
                }
            )

        ranked.sort(key=lambda entry: float(entry.get("score") or 0.0), reverse=True)
        return ranked[: max(1, top_k)]

    def _load_today_session_messages(self, character_id: str) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        session: Session = SessionLocal()
        try:
            rows = (
                session.query(History)
                .filter(
                    History.character_id == character_id,
                    History.timestamp >= day_start,
                )
                .order_by(History.timestamp.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content,
                    "timestamp": _normalize_utc_iso(row.timestamp),
                    "tags": [],
                }
                for row in rows
            ]
        finally:
            session.close()

    def _load_day_messages(self, character_id: str, day_start: datetime) -> List[Dict[str, Any]]:
        start = day_start if day_start.tzinfo else day_start.replace(tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        session: Session = SessionLocal()
        try:
            rows = (
                session.query(History)
                .filter(
                    History.character_id == character_id,
                    History.timestamp >= start,
                    History.timestamp < end,
                )
                .order_by(History.timestamp.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content,
                    "timestamp": _normalize_utc_iso(row.timestamp),
                    "tags": [],
                }
                for row in rows
            ]
        finally:
            session.close()

    def _load_day_messages_by_date(self, character_id: str, day_iso: str) -> List[Dict[str, Any]]:
        try:
            day_start = datetime.fromisoformat(day_iso)
        except Exception:
            return []

        if day_start.tzinfo is None:
            day_start = day_start.replace(tzinfo=timezone.utc)
        return self._load_day_messages(character_id, day_start)

    def _load_messages_by_ids(self, character_id: str, message_ids: Sequence[str]) -> List[Dict[str, Any]]:
        ids = [str(mid).strip() for mid in message_ids if str(mid).strip()]
        if not ids:
            return []

        session: Session = SessionLocal()
        try:
            rows = (
                session.query(History)
                .filter(
                    History.character_id == character_id,
                    History.id.in_(ids),
                )
                .order_by(History.timestamp.asc())
                .all()
            )
            return [
                {
                    "id": row.id,
                    "role": row.role,
                    "content": row.content,
                    "timestamp": _normalize_utc_iso(row.timestamp),
                    "tags": [],
                }
                for row in rows
            ]
        finally:
            session.close()

    def _derive_date_keys(self, query: str) -> List[str]:
        now = datetime.now(timezone.utc)
        query_lower = _safe_lower(query)
        keys = [now.date().isoformat(), now.strftime("%m-%d")]
        if "сегодня" in query_lower or "today" in query_lower:
            keys.append("today")
        if "вчера" in query_lower or "yesterday" in query_lower:
            keys.append((now - timedelta(days=1)).date().isoformat())
        return keys

