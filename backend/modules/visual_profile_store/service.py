from __future__ import annotations

import re

from modules.system.service import get_active_character_name
from modules.system.service import get_config_value, set_config_value
from modules.visual_intent_composer.schemas import VisualProfile


class VisualProfileStoreService:
    @staticmethod
    def _profile_key(character_name: str) -> str:
        value = str(character_name or "").strip()
        if not value:
            return "PAI"
        return re.sub(r"\s+", " ", value).strip()

    def load_profile(
        self,
        request_profile: dict | None = None,
        character_name: str | None = None,
    ) -> VisualProfile:
        cfg = get_config_value("synthesis.prompting", {}) or {}
        resolved_character_name = (
            str(character_name or "").strip()
            or str(get_active_character_name(default="PAI") or "PAI").strip()
            or "PAI"
        )
        raw_profile = cfg.get("visual_profile") if isinstance(cfg, dict) else {}
        if not isinstance(raw_profile, dict):
            raw_profile = {}
        per_character = cfg.get("per_character_visual_profiles") if isinstance(cfg, dict) else {}
        if not isinstance(per_character, dict):
            per_character = {}
        character_profile = per_character.get(self._profile_key(resolved_character_name))
        if not isinstance(character_profile, dict):
            character_profile = {}
        merged = {
            **raw_profile,
            **character_profile,
            **(request_profile if isinstance(request_profile, dict) else {}),
        }
        if not merged.get("appearance_textarea"):
            merged["appearance_textarea"] = str(cfg.get("appearance_prompt") or "").strip()
        merged["character_name"] = (
            str(merged.get("character_name") or resolved_character_name).strip()
            or resolved_character_name
        )
        return VisualProfile.model_validate(merged)

    def persist_profile(self, profile: VisualProfile) -> None:
        payload = profile.model_dump()
        character_name = str(payload.get("character_name") or get_active_character_name(default="PAI") or "PAI").strip() or "PAI"
        key = self._profile_key(character_name)
        prompting = get_config_value("synthesis.prompting", {}) or {}
        if not isinstance(prompting, dict):
            prompting = {}
        per_character = prompting.get("per_character_visual_profiles")
        if not isinstance(per_character, dict):
            per_character = {}
        per_character[key] = payload
        prompting["visual_profile"] = payload
        prompting["per_character_visual_profiles"] = per_character
        set_config_value("synthesis.prompting", prompting)

    def persist_generated_anchor_if_missing(self, generated: str) -> None:
        if not str(generated or "").strip():
            return
        profile = self.load_profile()
        if str(profile.appearance_textarea or "").strip():
            return
        updated = profile.model_copy(update={"appearance_textarea": str(generated).strip()})
        self.persist_profile(updated)


visual_profile_store_service = VisualProfileStoreService()
