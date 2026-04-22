from __future__ import annotations

import asyncio
import re
import time
from collections import defaultdict, deque
from difflib import SequenceMatcher
from math import sqrt
from typing import Any, Optional


class TelegramRateLimiter:
    """
    Sliding-window limiter for outbound Telegram messages.

    Controls:
    - per-chat max messages per window;
    - global max messages per window;
    - minimal delay between messages in one chat.
    """

    def __init__(
        self,
        *,
        per_chat_max_messages: int = 5,
        global_max_messages: int = 24,
        window_seconds: float = 15.0,
        min_delay_seconds: float = 0.7,
    ) -> None:
        self._per_chat_max_messages = max(1, int(per_chat_max_messages))
        self._global_max_messages = max(1, int(global_max_messages))
        self._window_seconds = max(0.1, float(window_seconds))
        self._min_delay_seconds = max(0.0, float(min_delay_seconds))
        self._chat_window: dict[int, deque[float]] = defaultdict(deque)
        self._global_window: deque[float] = deque()
        self._chat_last_sent_at: dict[int, float] = {}

    def reconfigure(
        self,
        *,
        per_chat_max_messages: int | None = None,
        global_max_messages: int | None = None,
        window_seconds: float | None = None,
        min_delay_seconds: float | None = None,
    ) -> None:
        if per_chat_max_messages is not None:
            self._per_chat_max_messages = max(1, int(per_chat_max_messages))
        if global_max_messages is not None:
            self._global_max_messages = max(1, int(global_max_messages))
        if window_seconds is not None:
            self._window_seconds = max(0.1, float(window_seconds))
        if min_delay_seconds is not None:
            self._min_delay_seconds = max(0.0, float(min_delay_seconds))

    async def wait_for_slot(self, chat_id: int) -> None:
        while True:
            now = time.monotonic()
            self._prune(now)

            chat_delay = self._window_delay(
                self._chat_window[chat_id],
                self._per_chat_max_messages,
                now,
            )
            global_delay = self._window_delay(
                self._global_window,
                self._global_max_messages,
                now,
            )
            inter_message_delay = max(
                0.0,
                (self._chat_last_sent_at.get(chat_id, 0.0) + self._min_delay_seconds)
                - now,
            )
            total_delay = max(chat_delay, global_delay, inter_message_delay)
            if total_delay <= 0:
                self._chat_window[chat_id].append(now)
                self._global_window.append(now)
                self._chat_last_sent_at[chat_id] = now
                return
            await asyncio.sleep(total_delay)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._global_window and self._global_window[0] < cutoff:
            self._global_window.popleft()
        for queue in list(self._chat_window.values()):
            while queue and queue[0] < cutoff:
                queue.popleft()

    def _window_delay(self, queue: deque[float], limit: int, now: float) -> float:
        if len(queue) < limit:
            return 0.0
        return max(0.0, queue[0] + self._window_seconds - now)


class TelegramRepeatGuard:
    """
    Prevents repeated assistant messages in one chat.

    Uses two checks:
    - SequenceMatcher ratio;
    - token Jaccard overlap.
    """

    _WORD_RE = re.compile(r"\w+", re.UNICODE)

    def __init__(
        self,
        *,
        history_size: int = 32,
        similarity_threshold: float = 0.92,
        jaccard_threshold: float = 0.88,
    ) -> None:
        self._history_size = max(1, int(history_size))
        self._similarity_threshold = float(similarity_threshold)
        self._jaccard_threshold = float(jaccard_threshold)
        self._history: dict[int, deque[str]] = defaultdict(
            lambda: deque(maxlen=self._history_size)
        )

    def reconfigure(
        self,
        *,
        history_size: int | None = None,
        similarity_threshold: float | None = None,
        jaccard_threshold: float | None = None,
    ) -> None:
        if history_size is not None and int(history_size) > 0:
            new_size = int(history_size)
            if new_size != self._history_size:
                self._history_size = new_size
                for chat_id, values in list(self._history.items()):
                    self._history[chat_id] = deque(values, maxlen=self._history_size)
        if similarity_threshold is not None:
            self._similarity_threshold = float(similarity_threshold)
        if jaccard_threshold is not None:
            self._jaccard_threshold = float(jaccard_threshold)

    def is_repetitive(self, chat_id: int, text: str) -> bool:
        candidate = self._normalize(text)
        if not candidate:
            return False
        candidate_tokens = set(self._WORD_RE.findall(candidate))
        for previous in self._history.get(chat_id, ()):
            if SequenceMatcher(None, previous, candidate).ratio() >= self._similarity_threshold:
                return True
            previous_tokens = set(self._WORD_RE.findall(previous))
            if not previous_tokens and not candidate_tokens:
                continue
            union = previous_tokens | candidate_tokens
            if not union:
                continue
            jaccard = len(previous_tokens & candidate_tokens) / len(union)
            if jaccard >= self._jaccard_threshold:
                return True
        return False

    def remember(self, chat_id: int, text: str) -> None:
        value = self._normalize(text)
        if not value:
            return
        self._history[chat_id].append(value)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").strip().lower().split())


class TelegramSemanticRepeatGuard:
    """
    Semantic anti-repeat guard using embedding cosine similarity.

    Quality-first defaults are based on kuni-like thresholds.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        history_size: int = 32,
        max_similarity_threshold: float = 0.75,
        avg_similarity_threshold: float = 0.73,
        provider: str = "auto",
        model: str = "nomic-embed-text",
    ) -> None:
        self._enabled = bool(enabled)
        self._history_size = max(1, int(history_size))
        self._max_similarity_threshold = float(max_similarity_threshold)
        self._avg_similarity_threshold = float(avg_similarity_threshold)
        self._provider = str(provider or "auto").strip().lower() or "auto"
        self._model = str(model or "nomic-embed-text").strip() or "nomic-embed-text"
        self._history: dict[int, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=self._history_size)
        )
        self._embed_fn = None

    def reconfigure(
        self,
        *,
        enabled: bool | None = None,
        history_size: int | None = None,
        max_similarity_threshold: float | None = None,
        avg_similarity_threshold: float | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        if enabled is not None:
            self._enabled = bool(enabled)
        if history_size is not None and int(history_size) > 0:
            new_size = int(history_size)
            if new_size != self._history_size:
                self._history_size = new_size
                for chat_id, values in list(self._history.items()):
                    self._history[chat_id] = deque(values, maxlen=self._history_size)
        if max_similarity_threshold is not None:
            self._max_similarity_threshold = float(max_similarity_threshold)
        if avg_similarity_threshold is not None:
            self._avg_similarity_threshold = float(avg_similarity_threshold)
        if provider is not None:
            self._provider = str(provider or "auto").strip().lower() or "auto"
        if model is not None:
            self._model = str(model or "nomic-embed-text").strip() or "nomic-embed-text"

    def is_repetitive(self, chat_id: int, text: str) -> bool:
        if not self._enabled:
            return False
        candidate = self._normalize(text)
        if not candidate:
            return False
        candidate_embedding = self._embedding(candidate)
        if not candidate_embedding:
            return False

        similarities: list[float] = []
        for item in self._history.get(chat_id, ()):
            previous_embedding = item.get("embedding")
            if not isinstance(previous_embedding, list) or not previous_embedding:
                continue
            score = self._cosine_similarity(candidate_embedding, previous_embedding)
            if score is None:
                continue
            similarities.append(score)
            if score >= self._max_similarity_threshold:
                return True

        if not similarities:
            return False
        avg = sum(similarities) / len(similarities)
        return avg >= self._avg_similarity_threshold

    def remember(self, chat_id: int, text: str) -> None:
        candidate = self._normalize(text)
        if not candidate:
            return
        embedding = self._embedding(candidate)
        if not embedding:
            return
        self._history[chat_id].append({"text": candidate, "embedding": embedding})

    def _embedding(self, text: str) -> Optional[list[float]]:
        embed_fn = self._get_embedding_fn()
        if embed_fn is None:
            return None
        try:
            vector = embed_fn(text, provider=self._provider, model=self._model)
        except Exception:
            return None
        if not isinstance(vector, list) or not vector:
            return None
        try:
            return [float(value) for value in vector]
        except Exception:
            return None

    def _get_embedding_fn(self):
        if self._embed_fn is not None:
            return self._embed_fn
        try:
            from modules.memory.embeddings import get_embedding  # lazy import
        except Exception:
            self._embed_fn = None
            return None
        self._embed_fn = get_embedding
        return self._embed_fn

    @staticmethod
    def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> Optional[float]:
        length = min(len(vec_a), len(vec_b))
        if length <= 0:
            return None
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for idx in range(length):
            a = float(vec_a[idx])
            b = float(vec_b[idx])
            dot += a * b
            norm_a += a * a
            norm_b += b * b
        if norm_a <= 0.0 or norm_b <= 0.0:
            return None
        return dot / (sqrt(norm_a) * sqrt(norm_b))

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join((text or "").strip().lower().split())
