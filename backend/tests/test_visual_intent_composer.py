from modules.visual_intent_composer import (
    VisualIntentComposerService,
    VisualIntentInput,
    VisualProfile,
)
from modules.visual_prompt_builder import visual_prompt_builder_service


def _payload(**overrides):
    base = VisualIntentInput(
        emotion_state={
            "current_emotion": "thoughtful",
            "emotional_intensity": 0.42,
            "mood_vector": {
                "warmth": 0.71,
                "playfulness": 0.18,
                "tiredness": 0.54,
                "closeness": 0.66,
                "sadness": 0.12,
            },
        },
        relation_state={
            "target_user_id": "owner",
            "relation_type": "owner",
            "trust_score": 0.95,
            "affinity_score": 0.88,
            "resentment_score": 0.03,
            "disclosure_mode": "open",
        },
        recent_context={
            "recent_topics": ["news", "late evening check-in"],
            "recent_summary": "Reflective evening after reading heavy news.",
            "last_topic": "news",
            "recent_tone_summary": "warm but slightly tired",
            "last_interaction_gap_hours": 3.2,
        },
        world_state={
            "local_time": "23:17",
            "time_of_day": "late_evening",
            "day_period": "night",
            "season": "winter",
            "weather": "cold_clear",
            "device_mode": "phone",
            "location_mode": "home",
        },
        self_expression_context={
            "current_mode": "initiative",
            "purpose_hint": "check_in",
            "selection_seed": 7,
        },
        visual_profile=VisualProfile(
            character_name="PAI",
            appearance_textarea=(
                "adult anime woman, long deep blue hair with vibrant pink gradient tips, "
                "bright expressive purple eyes, black over-ear headphones with glowing neon cat ears, "
                "cozy cyber-home aesthetic"
            ),
            default_outfit="cozy black crop top, casual homewear",
            style_preset="anime",
            render_profile="default_anime",
            allow_self_images=True,
            allow_environment_images=True,
            allow_symbolic_images=True,
        ),
    )
    return base.model_copy(update=overrides)


def test_visual_intent_composer_prefers_self_for_high_trust_evening_checkin():
    service = VisualIntentComposerService()
    plan = service.compose(_payload())

    assert plan.subject_mode == "self"
    assert plan.distance in {"close_selfie", "portrait"}
    assert "warm" in plan.tone
    assert plan.setting == "cozy_winter_bedroom"
    assert "warm_bedside_light" in plan.lighting
    assert plan.composition_pool_id


def test_visual_intent_composer_can_choose_environment_only_for_low_intimacy_rainy_morning():
    service = VisualIntentComposerService()
    payload = _payload(
        relation_state={
            "target_user_id": "guest",
            "relation_type": "neutral",
            "trust_score": 0.25,
            "affinity_score": 0.22,
            "resentment_score": 0.0,
            "disclosure_mode": "guarded",
        },
        emotion_state={
            "current_emotion": "quiet",
            "mood_vector": {"warmth": 0.3, "playfulness": 0.05, "tiredness": 0.64, "closeness": 0.18, "sadness": 0.21},
        },
        world_state={
            "local_time": "08:40",
            "time_of_day": "morning",
            "day_period": "morning",
            "season": "spring",
            "weather": "rainy",
            "device_mode": "desktop",
            "location_mode": "home",
        },
        self_expression_context={"current_mode": "reflection", "purpose_hint": "atmosphere_share"},
        visual_profile=VisualProfile(
            character_name="PAI",
            appearance_textarea="adult anime woman, blue hair, violet eyes",
            style_preset="anime",
            render_profile="default_anime",
            selfie_bias=0.05,
            environment_bias=0.90,
            symbolic_bias=0.05,
            allow_self_images=True,
            allow_environment_images=True,
            allow_symbolic_images=True,
        ),
    )
    plan = service.compose(payload)

    assert plan.subject_mode == "environment_only"
    assert plan.generator_mode == "environment_scene"


def test_visual_intent_composer_generates_stable_fallback_appearance_when_missing():
    service = VisualIntentComposerService()
    payload = _payload(
        visual_profile=VisualProfile(
            character_name="CustomPAI",
            appearance_textarea="",
            style_preset="anime",
            render_profile="default_anime",
        )
    )
    plan = service.compose(payload)

    assert plan.generated_appearance
    assert "anime woman" in plan.generated_appearance


def test_visual_prompt_builder_uses_appearance_anchor_and_plan():
    service = VisualIntentComposerService()
    payload = _payload()
    plan = service.compose(payload)
    prompt = visual_prompt_builder_service.build_prompt(
        profile=payload.visual_profile,
        plan=plan,
    )

    assert "deep blue hair" in prompt
    assert "warm bedside light" in prompt.lower()
    assert "cozy black crop top" in prompt.lower()


def test_visual_intent_composer_uses_pool_override_when_provided():
    service = VisualIntentComposerService()
    payload = _payload(
        visual_profile=VisualProfile(
            character_name="PAI",
            appearance_textarea="adult anime woman, violet eyes, midnight blue hair",
            selfie_composition_pool_override="""
selfie_composition_pool:
  - id: override_close
    weight: 1.0
    prompt: front-facing selfie, very close, candid
""",
            style_preset="anime",
            render_profile="default_anime",
        ),
        self_expression_context={
            "current_mode": "initiative",
            "purpose_hint": "check_in",
            "selection_seed": 42,
        },
    )
    plan = service.compose(payload)

    assert plan.composition_pool_id == "override_close"
    assert "front-facing selfie" in plan.composition_prompt
