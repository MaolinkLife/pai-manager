from __future__ import annotations

from modules.system.service import get_active_character_name
from modules.system.service import get_config_value, set_config_value
from modules.visual_intent_composer.schemas import VisualProfile


class VisualProfileStoreService:
    def load_profile(self, request_profile: dict | None = None) -> VisualProfile:
        cfg = get_config_value("synthesis.prompting", {}) or {}
        character_name = str(get_active_character_name(default="PAI") or "PAI").strip() or "PAI"
        raw_profile = cfg.get("visual_profile") if isinstance(cfg, dict) else {}
        if not isinstance(raw_profile, dict):
            raw_profile = {}
        merged = {
            **raw_profile,
            **(request_profile if isinstance(request_profile, dict) else {}),
        }
        if not merged.get("appearance_textarea"):
            merged["appearance_textarea"] = str(cfg.get("appearance_prompt") or "").strip()
        if not merged.get("character_name"):
            merged["character_name"] = character_name
        return VisualProfile.model_validate(merged)

    def persist_profile(self, profile: VisualProfile) -> None:
        set_config_value("synthesis.prompting.visual_profile", profile.model_dump())

    def persist_generated_anchor_if_missing(self, generated: str) -> None:
        if not str(generated or "").strip():
            return
        legacy = str(get_config_value("synthesis.prompting.appearance_prompt", "") or "").strip()
        if not legacy:
            set_config_value("synthesis.prompting.appearance_prompt", str(generated).strip())


visual_profile_store_service = VisualProfileStoreService()
