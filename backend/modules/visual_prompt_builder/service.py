from __future__ import annotations

from modules.visual_intent_composer.schemas import VisualIntentPlan, VisualProfile

from .templates import (
    DEFAULT_NEGATIVE_PROMPT,
    QUALITY_PROMPT,
    STYLE_PRESET_PROMPTS,
    join_parts,
)


class VisualPromptBuilderService:
    def build_prompt_pair(
        self,
        *,
        profile: VisualProfile,
        plan: VisualIntentPlan,
    ) -> tuple[str, str]:
        style_prompt = STYLE_PRESET_PROMPTS.get(
            str(profile.style_preset or "").strip().lower(),
            STYLE_PRESET_PROMPTS["anime"],
        )
        setting_prompt = (
            str(profile.default_environment or "").strip()
            or str(plan.setting or "").replace("_", " ").strip()
        )
        composition_prompt = str(plan.composition_prompt or "").strip()
        if not composition_prompt:
            composition_prompt = (
                str(plan.composition.get("pool_prompt") or "").strip()
                or join_parts(
                    [
                        str(plan.composition.get("framing") or ""),
                        str(plan.composition.get("angle") or ""),
                        str(plan.composition.get("camera_energy") or ""),
                    ]
                )
            )

        positive = join_parts(
            [
                str(profile.appearance_textarea or "").strip(),
                str(profile.default_outfit or "").strip(),
                composition_prompt,
                setting_prompt,
                join_parts([item.replace("_", " ") for item in plan.lighting]),
                style_prompt,
                QUALITY_PROMPT,
            ]
        )
        negative = DEFAULT_NEGATIVE_PROMPT
        return positive, negative

    def build_prompt(
        self,
        *,
        profile: VisualProfile,
        plan: VisualIntentPlan,
    ) -> str:
        positive, _negative = self.build_prompt_pair(profile=profile, plan=plan)
        return positive


visual_prompt_builder_service = VisualPromptBuilderService()
