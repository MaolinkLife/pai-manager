from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict


@dataclass(slots=True)
class _VisualHistoryEntry:
    subject_mode: str
    composition_pool_id: str
    setting: str
    lighting_key: str


class VisualHistoryCacheService:
    def __init__(self, max_items: int = 48) -> None:
        self._max_items = max(8, int(max_items))
        self._history: Dict[str, Deque[_VisualHistoryEntry]] = {}

    def register(
        self,
        *,
        profile_key: str,
        subject_mode: str,
        composition_pool_id: str,
        setting: str,
        lighting: list[str],
    ) -> None:
        key = str(profile_key or "default")
        store = self._history.setdefault(key, deque(maxlen=self._max_items))
        lighting_key = "|".join(sorted(str(item or "").strip().lower() for item in (lighting or [])))
        store.append(
            _VisualHistoryEntry(
                subject_mode=str(subject_mode or "").strip().lower(),
                composition_pool_id=str(composition_pool_id or "").strip().lower(),
                setting=str(setting or "").strip().lower(),
                lighting_key=lighting_key,
            )
        )

    def recent_counts(self, *, profile_key: str, lookback: int = 12) -> dict[str, dict[str, int]]:
        key = str(profile_key or "default")
        store = self._history.get(key)
        if not store:
            return {
                "subject_modes": {},
                "composition_pool_ids": {},
                "settings": {},
                "lighting": {},
            }
        subject_modes: dict[str, int] = {}
        composition_pool_ids: dict[str, int] = {}
        settings: dict[str, int] = {}
        lighting: dict[str, int] = {}
        for entry in list(store)[-max(1, int(lookback)) :]:
            subject_modes[entry.subject_mode] = subject_modes.get(entry.subject_mode, 0) + 1
            composition_pool_ids[entry.composition_pool_id] = composition_pool_ids.get(entry.composition_pool_id, 0) + 1
            settings[entry.setting] = settings.get(entry.setting, 0) + 1
            lighting[entry.lighting_key] = lighting.get(entry.lighting_key, 0) + 1
        return {
            "subject_modes": subject_modes,
            "composition_pool_ids": composition_pool_ids,
            "settings": settings,
            "lighting": lighting,
        }


visual_history_cache_service = VisualHistoryCacheService()
