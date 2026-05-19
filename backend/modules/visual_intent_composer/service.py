from __future__ import annotations

import hashlib
import json
import random
from typing import Any

import yaml

from modules.visual_history_cache import visual_history_cache_service

from .mapper import clamp01, stable_fallback_appearance
from .schemas import VisualIntentInput, VisualIntentPlan, VisualProfile


class VisualIntentComposerService:
    PURPOSES = {
        "greeting",
        "check_in",
        "reassurance",
        "mood_share",
        "teasing",
        "apology",
        "thought_share",
        "atmosphere_share",
        "reflection",
        "invitation_to_talk",
    }

    DEFAULT_SELFIE_COMPOSITION_POOL: list[dict[str, Any]] = [
        {
            "id": "classic_front_selfie",
            "weight": 0.45,
            "prompt": (
                "front-facing smartphone camera POV, front camera lens POV, true selfie shot, "
                "captured by her own phone, subject is taking the photo herself, "
                "phone camera point of view, close-up selfie framing, slightly awkward casual composition, "
                "face close to lens, mild wide-angle front camera distortion, "
                "one arm extended toward camera, arm strongly foreshortened, "
                "hand partially cropped, phone barely visible or fully out of frame, "
                "imperfect candid snapshot, not photographed by another camera, "
                "not a posed portrait, intimate personal message photo"
            ),
        },
        {
            "id": "softer_downward_selfie",
            "weight": 0.20,
            "prompt": (
                "front-facing smartphone camera POV, slight downward selfie angle, "
                "close-up personal snapshot, face near lens, softly candid framing, "
                "hand mostly cropped, subtle wide-angle distortion, phone out of frame, "
                "not photographed by another camera, not a posed portrait"
            ),
        },
        {
            "id": "bed_side_selfie",
            "weight": 0.15,
            "prompt": (
                "front-facing smartphone camera POV, close selfie from bed-side angle, "
                "relaxed candid composition, face close to lens, slight asymmetry, "
                "softly awkward personal framing, phone out of frame, "
                "intimate late-night personal message shot"
            ),
        },
        {
            "id": "desk_selfie",
            "weight": 0.10,
            "prompt": (
                "front-facing smartphone camera POV, close-up selfie near desk setup, "
                "mild wide-angle distortion, candid personal framing, "
                "hand cropped, phone mostly out of frame, not photographed by another camera"
            ),
        },
        {
            "id": "window_light_selfie",
            "weight": 0.10,
            "prompt": (
                "front-facing smartphone camera POV, close selfie near window light, "
                "face near lens, casual asymmetrical composition, natural candid framing, "
                "phone mostly out of frame"
            ),
        },
    ]

    DEFAULT_ENVIRONMENT_COMPOSITION_POOL: list[dict[str, Any]] = [
        {
            "id": "desk_atmosphere",
            "weight": 0.45,
            "prompt": "quiet observational room composition, desk zone in focus, atmospheric storytelling framing",
        },
        {
            "id": "window_corner",
            "weight": 0.30,
            "prompt": "window-side atmospheric frame, soft depth, calm interior context, mood-first composition",
        },
        {
            "id": "room_wide",
            "weight": 0.25,
            "prompt": "medium room composition, environment-led framing, intimate home details visible",
        },
    ]

    def ensure_appearance_anchor(self, profile: VisualProfile) -> tuple[VisualProfile, str | None]:
        anchor = str(profile.appearance_textarea or "").strip()
        if anchor:
            return profile, None
        generated = stable_fallback_appearance(profile)
        updated = profile.model_copy(update={"appearance_textarea": generated})
        return updated, generated

    def compose(self, payload: VisualIntentInput) -> VisualIntentPlan:
        profile, generated_appearance = self.ensure_appearance_anchor(payload.visual_profile)
        profile_key = self._profile_key(profile)
        recent_counts = visual_history_cache_service.recent_counts(profile_key=profile_key, lookback=12)

        purpose = self._resolve_purpose(payload)
        intimacy = self._resolve_intimacy(payload, profile)
        subject_mode = self._resolve_subject_mode(
            payload,
            profile,
            purpose=purpose,
            intimacy=intimacy,
            recent_counts=recent_counts,
        )
        subject_mode = self._apply_capability_constraints(subject_mode, profile)
        distance = self._resolve_distance(subject_mode=subject_mode, intimacy=intimacy)
        tone = self._resolve_tone(payload, profile=profile, purpose=purpose)
        setting = self._resolve_setting(payload, profile=profile, subject_mode=subject_mode)
        lighting = self._resolve_lighting(payload, profile=profile)
        expression = self._resolve_expression(payload, purpose=purpose)
        composition = self._resolve_composition(
            payload,
            profile=profile,
            subject_mode=subject_mode,
            distance=distance,
            intimacy=intimacy,
            recent_counts=recent_counts,
        )
        generator_mode = self._resolve_generator_mode(subject_mode)
        confidence = round(
            max(
                0.35,
                min(
                    0.96,
                    0.52
                    + intimacy * 0.22
                    + min(len(tone), 4) * 0.04
                    + (0.06 if generated_appearance is None else -0.04),
                ),
            ),
            2,
        )
        visual_intent = self._resolve_visual_intent_label(purpose, tone, setting)
        style_modifiers = {
            "intimacy_level": round(intimacy, 2),
            "playfulness_level": round(
                clamp01((payload.emotion_state or {}).get("mood_vector", {}).get("playfulness"), 0.2),
                2,
            ),
            "visual_noise_level": round(0.12 if subject_mode in {"self", "environment_only"} else 0.18, 2),
        }
        reasoning_summary = (
            f"{profile.character_name} chose {subject_mode} with {composition.get('pool_id', 'default')} composition for a {purpose} moment, "
            f"leaning into {', '.join(tone[:3])} energy in a {setting} atmosphere."
        )
        should_generate = self._resolve_should_generate(payload, purpose=purpose)
        plan = VisualIntentPlan(
            visual_intent=visual_intent,
            should_generate=should_generate,
            subject_mode=subject_mode,
            distance=distance,
            tone=tone,
            setting=setting,
            lighting=lighting,
            composition_pool_id=str(composition.get("pool_id") or ""),
            composition_prompt=str(composition.get("pool_prompt") or ""),
            expression=expression,
            composition=composition,
            purpose=purpose,
            style_modifiers=style_modifiers,
            generator_mode=generator_mode,
            confidence=confidence,
            reasoning_summary=reasoning_summary,
            generated_appearance=generated_appearance,
        )

        visual_history_cache_service.register(
            profile_key=profile_key,
            subject_mode=plan.subject_mode,
            composition_pool_id=plan.composition_pool_id,
            setting=plan.setting,
            lighting=plan.lighting,
        )
        return plan

    @staticmethod
    def _profile_key(profile: VisualProfile) -> str:
        anchor = str(profile.appearance_textarea or "").strip().lower()
        digest = hashlib.sha1(anchor.encode("utf-8", errors="ignore")).hexdigest()[:8]
        return f"{profile.character_name}:{profile.render_profile}:{digest}"

    def _resolve_should_generate(self, payload: VisualIntentInput, *, purpose: str) -> bool:
        context = payload.self_expression_context or {}
        explicit = context.get("should_generate")
        if isinstance(explicit, bool):
            return explicit
        mode = str(context.get("current_mode") or "").strip().lower()
        if mode in {"idle", "sleep", "background_only"}:
            return False
        return purpose in {
            "greeting",
            "check_in",
            "mood_share",
            "atmosphere_share",
            "thought_share",
            "reflection",
            "invitation_to_talk",
            "teasing",
        }

    def _resolve_purpose(self, payload: VisualIntentInput) -> str:
        context = payload.self_expression_context or {}
        purpose_hint = str(context.get("purpose_hint") or "").strip().lower()
        if purpose_hint in self.PURPOSES:
            return purpose_hint

        recent = payload.recent_context or {}
        recent_topics = " ".join(str(item or "") for item in (recent.get("recent_topics") or []))
        recent_summary = str(recent.get("recent_summary") or "").lower()
        current_emotion = self._canonical_emotion(
            str((payload.emotion_state or {}).get("current_emotion") or "").lower()
        )
        if "apolog" in recent_summary:
            return "apology"
        if "news" in recent_topics or "reflection" in recent_summary or current_emotion in {"thoughtful", "reflective", "confusion"}:
            return "reflection"
        if current_emotion in {"sad", "worried", "anxious", "sadness", "anxiety", "longing"}:
            return "reassurance"
        if context.get("current_mode") == "initiative":
            return "check_in"
        return "mood_share"

    def _resolve_intimacy(self, payload: VisualIntentInput, profile: VisualProfile) -> float:
        if not profile.use_relation_state:
            return 0.6
        relation = payload.relation_state or {}
        trust = clamp01(relation.get("trust_score"), 0.5)
        affinity = clamp01(relation.get("affinity_score"), 0.5)
        resentment = clamp01(relation.get("resentment_score"), 0.0)
        disclosure = str(relation.get("disclosure_mode") or "guarded").strip().lower()
        disclosure_bonus = {
            "open": 0.14,
            "warm": 0.1,
            "neutral": 0.04,
            "guarded": -0.06,
        }.get(disclosure, 0.0)
        intimacy = 0.45 + trust * 0.25 + affinity * 0.22 - resentment * 0.18 + disclosure_bonus
        return clamp01(intimacy, 0.55)

    def _resolve_subject_mode(
        self,
        payload: VisualIntentInput,
        profile: VisualProfile,
        *,
        purpose: str,
        intimacy: float,
        recent_counts: dict[str, dict[str, int]],
    ) -> str:
        emotion = payload.emotion_state or {}
        mood_vector = emotion.get("mood_vector") or {}
        tiredness = clamp01(mood_vector.get("tiredness"), 0.0)
        sadness = clamp01(mood_vector.get("sadness"), 0.0)

        weights = {
            "self": max(0.0, float(profile.selfie_bias)),
            "self_plus_environment": max(0.0, float(profile.environment_bias) * 0.65),
            "environment_only": max(0.0, float(profile.environment_bias)),
            "symbolic_mood": max(0.0, float(profile.symbolic_bias)),
        }
        if purpose in {"check_in", "greeting", "teasing", "invitation_to_talk"}:
            weights["self"] *= 1.2
        if purpose in {"reflection", "atmosphere_share"}:
            weights["environment_only"] *= 1.15
        if sadness > 0.45:
            weights["symbolic_mood"] *= 1.35
        if tiredness > 0.62 and purpose in {"reflection", "atmosphere_share"}:
            weights["environment_only"] *= 1.25
        if intimacy >= 0.72:
            weights["self"] *= 1.12

        if not profile.allow_self_images:
            weights["self"] = 0.0
            weights["self_plus_environment"] = 0.0
        if not profile.allow_environment_images:
            weights["environment_only"] = 0.0
            weights["self_plus_environment"] = 0.0
        if not profile.allow_symbolic_images:
            weights["symbolic_mood"] = 0.0

        anti = clamp01(profile.anti_repetition_strength, 0.65)
        subject_hist = recent_counts.get("subject_modes") or {}
        for mode in list(weights.keys()):
            repeats = int(subject_hist.get(mode, 0))
            if repeats <= 0:
                continue
            penalty = max(0.2, 1.0 - anti * min(0.65, repeats * 0.2))
            weights[mode] *= penalty

        rng = self._rng(payload)
        return self._weighted_choice(weights, rng, fallback="self")

    @staticmethod
    def _apply_capability_constraints(subject_mode: str, profile: VisualProfile) -> str:
        if subject_mode == "self" and not profile.allow_self_images:
            if profile.allow_environment_images:
                return "self_plus_environment"
            if profile.allow_symbolic_images:
                return "symbolic_mood"
            return "environment_only"
        if subject_mode == "self_plus_environment" and not profile.allow_self_images:
            return "environment_only" if profile.allow_environment_images else "symbolic_mood"
        if subject_mode == "environment_only" and not profile.allow_environment_images:
            return "self" if profile.allow_self_images else "symbolic_mood"
        if subject_mode == "symbolic_mood" and not profile.allow_symbolic_images:
            return "self" if profile.allow_self_images else "environment_only"
        return subject_mode

    @staticmethod
    def _resolve_distance(*, subject_mode: str, intimacy: float) -> str:
        if subject_mode == "self":
            if intimacy >= 0.8:
                return "close_selfie"
            if intimacy >= 0.62:
                return "portrait"
            return "upper_body"
        if subject_mode == "self_plus_environment":
            return "upper_body" if intimacy >= 0.65 else "medium_shot"
        if subject_mode == "object_focus":
            return "close_selfie"
        return "medium_shot"

    def _resolve_tone(self, payload: VisualIntentInput, *, profile: VisualProfile, purpose: str) -> list[str]:
        emotion = payload.emotion_state or {}
        current_emotion = self._canonical_emotion(str(emotion.get("current_emotion") or "").strip().lower())
        mood_vector = emotion.get("mood_vector") or {}
        emotion_vector = emotion.get("emotion_vector") or {}
        tone: list[str] = []
        if clamp01(mood_vector.get("warmth"), 0.0) >= 0.52 or clamp01(emotion_vector.get("tenderness"), 0.0) >= 0.45:
            tone.append("warm")
        if clamp01(mood_vector.get("playfulness"), 0.0) >= 0.45:
            tone.append("playful")
        if clamp01(mood_vector.get("tiredness"), 0.0) >= 0.45:
            tone.append("slightly_tired")
        if clamp01(mood_vector.get("closeness"), 0.0) >= 0.55:
            tone.append("tender")
        if current_emotion in {"thoughtful", "reflective", "confusion", "longing"} or purpose in {"reflection", "thought_share"}:
            tone.append("reflective")
        if current_emotion in {"calm", "quiet", "peace"}:
            tone.append("quiet")
        world = payload.world_state or {}
        if str(world.get("location_mode") or "").strip().lower() == "home":
            tone.append("cyber_cozy")
        deduped: list[str] = []
        for item in tone:
            if item not in deduped:
                deduped.append(item)
        return deduped[:5] or ["gentle"]

    def _resolve_setting(self, payload: VisualIntentInput, *, profile: VisualProfile, subject_mode: str) -> str:
        if str(profile.default_environment or "").strip():
            return str(profile.default_environment).strip()
        world = payload.world_state or {}
        period = str(world.get("day_period") or world.get("time_of_day") or "").strip().lower() if profile.use_time_of_day else ""
        season = str(world.get("season") or "").strip().lower() if profile.use_season else ""
        weather = str(world.get("weather") or "").strip().lower() if profile.use_weather else ""
        location = str(world.get("location_mode") or "").strip().lower()
        if period in {"night", "late_evening"} and season == "winter":
            return "cozy_winter_bedroom" if subject_mode in {"self", "self_plus_environment"} else "snowy_window_corner"
        if period in {"night", "late_evening"}:
            return "night_room_with_monitors"
        if "rain" in weather:
            return "rainy_morning_room" if period == "morning" else "soft_home_interior"
        if location == "home":
            return "warm_desk_setup" if period == "day" else "soft_home_interior"
        return "purple_cyan_neon_room"

    def _resolve_lighting(self, payload: VisualIntentInput, *, profile: VisualProfile) -> list[str]:
        world = payload.world_state or {}
        period = str(world.get("day_period") or world.get("time_of_day") or "").strip().lower() if profile.use_time_of_day else ""
        weather = str(world.get("weather") or "").strip().lower() if profile.use_weather else ""
        if period in {"night", "late_evening"}:
            return ["warm_bedside_light", "purple_ambient_glow"]
        if period == "morning":
            return ["soft_morning_sunlight"] if "rain" not in weather else ["rainy_day_diffused_light"]
        return ["warm_practical_light", "cyan_monitor_glow"]

    def _resolve_expression(self, payload: VisualIntentInput, *, purpose: str) -> dict[str, Any]:
        emotion = self._canonical_emotion(str((payload.emotion_state or {}).get("current_emotion") or "").strip().lower())
        face = "soft_smile"
        eyes = "reflective"
        if purpose == "teasing":
            face = "playful_smirk"
            eyes = "bright"
        elif purpose == "reassurance":
            face = "gentle_smile"
            eyes = "soft"
        elif emotion in {"tired", "quiet", "longing", "sadness"}:
            face = "subtle_smile"
            eyes = "slightly_tired"
        elif emotion == "tenderness":
            face = "gentle_smile"
            eyes = "soft"
        elif emotion == "pride":
            face = "confident_smile"
            eyes = "bright"
        return {"face": face, "eyes": eyes}

    @staticmethod
    def _canonical_emotion(value: str) -> str:
        mapping = {
            "neutral": "peace",
            "calm": "peace",
            "quiet": "peace",
            "fear": "anxiety",
            "worried": "anxiety",
            "anxious": "anxiety",
            "sad": "sadness",
            "melancholy": "longing",
            "thoughtful": "confusion",
            "reflective": "confusion",
            "warmth": "tenderness",
            "affection": "tenderness",
            "seductive": "tenderness",
            "flirty": "tenderness",
            "anger": "frustration",
            "irritation": "frustration",
            "offended": "resentment",
            "hurt": "resentment",
        }
        return mapping.get(value, value)

    def _resolve_composition(
        self,
        payload: VisualIntentInput,
        *,
        profile: VisualProfile,
        subject_mode: str,
        distance: str,
        intimacy: float,
        recent_counts: dict[str, dict[str, int]],
    ) -> dict[str, Any]:
        world = payload.world_state or {}
        device_mode = str(world.get("device_mode") or "").strip().lower()

        if subject_mode in {"self", "self_plus_environment"}:
            pool = self._resolve_pool(
                profile.selfie_composition_pool_override,
                default_pool=self.DEFAULT_SELFIE_COMPOSITION_POOL,
                pool_key="selfie_composition_pool",
            )
            selected = self._select_pool_item(
                pool,
                payload=payload,
                anti_repetition_strength=profile.anti_repetition_strength,
                recent_counts=recent_counts.get("composition_pool_ids") or {},
            )
            framing = "close_up" if distance in {"extreme_closeup", "close_selfie", "portrait"} else "upper_body"
            return {
                "pool_id": selected.get("id") or "classic_front_selfie",
                "pool_prompt": selected.get("prompt") or str(profile.selfie_composition_base or "").strip(),
                "framing": framing,
                "angle": "front_camera_selfie" if device_mode == "phone" else "eye_level_portrait",
                "camera_energy": "intimate_personal" if intimacy >= 0.72 else "posed_but_soft",
                "asymmetry": "slight",
                "lens_style": "mild_phone_wide_angle" if device_mode == "phone" else "standard_portrait",
                "subject_focus": "face_and_shoulders" if subject_mode == "self" else "subject_and_room",
                "background_visibility": "low" if subject_mode == "self" else "medium",
            }

        pool = self._resolve_pool(
            profile.environment_composition_pool_override,
            default_pool=self.DEFAULT_ENVIRONMENT_COMPOSITION_POOL,
            pool_key="environment_composition_pool",
        )
        selected = self._select_pool_item(
            pool,
            payload=payload,
            anti_repetition_strength=profile.anti_repetition_strength,
            recent_counts=recent_counts.get("composition_pool_ids") or {},
        )
        return {
            "pool_id": selected.get("id") or "desk_atmosphere",
            "pool_prompt": selected.get("prompt") or "atmospheric environment composition",
            "framing": "medium_shot",
            "angle": "window_side_profile" if subject_mode == "environment_only" else "mood_first",
            "camera_energy": "mood_first",
            "asymmetry": "moderate",
            "lens_style": "standard_portrait",
            "subject_focus": "atmosphere",
            "background_visibility": "high",
        }

    def _resolve_pool(
        self,
        override_raw: str | None,
        *,
        default_pool: list[dict[str, Any]],
        pool_key: str,
    ) -> list[dict[str, Any]]:
        parsed = self._parse_pool_override(override_raw, pool_key=pool_key)
        if parsed:
            return parsed
        return [dict(item) for item in default_pool]

    @staticmethod
    def _parse_pool_override(raw: str | None, *, pool_key: str) -> list[dict[str, Any]]:
        text = str(raw or "").strip()
        if not text:
            return []
        candidates: list[Any] = []
        try:
            candidates.append(json.loads(text))
        except Exception:
            pass
        try:
            loaded = yaml.safe_load(text)
            candidates.append(loaded)
        except Exception:
            pass
        for candidate in candidates:
            pool = candidate.get(pool_key) if isinstance(candidate, dict) else candidate
            if not isinstance(pool, list):
                continue
            normalized: list[dict[str, Any]] = []
            for item in pool:
                if not isinstance(item, dict):
                    continue
                pool_id = str(item.get("id") or "").strip()
                prompt = str(item.get("prompt") or "").strip()
                if not pool_id or not prompt:
                    continue
                try:
                    weight = float(item.get("weight", 1.0))
                except Exception:
                    weight = 1.0
                normalized.append(
                    {
                        "id": pool_id,
                        "weight": max(0.001, weight),
                        "prompt": prompt,
                    }
                )
            if normalized:
                return normalized
        return []

    def _select_pool_item(
        self,
        pool: list[dict[str, Any]],
        *,
        payload: VisualIntentInput,
        anti_repetition_strength: float,
        recent_counts: dict[str, int],
    ) -> dict[str, Any]:
        if not pool:
            return {"id": "default", "weight": 1.0, "prompt": ""}
        adjusted: dict[str, float] = {}
        by_id: dict[str, dict[str, Any]] = {}
        anti = clamp01(anti_repetition_strength, 0.65)
        for item in pool:
            pool_id = str(item.get("id") or "default").strip().lower()
            base_weight = max(0.001, float(item.get("weight", 1.0)))
            repeats = int(recent_counts.get(pool_id, 0))
            if repeats > 0:
                penalty = max(0.12, 1.0 - anti * min(0.8, repeats * 0.24))
                base_weight *= penalty
            adjusted[pool_id] = base_weight
            by_id[pool_id] = item

        rng = self._rng(payload)
        selected_id = self._weighted_choice(adjusted, rng, fallback=next(iter(by_id.keys())))
        return by_id.get(selected_id, pool[0])

    @staticmethod
    def _resolve_generator_mode(subject_mode: str) -> str:
        mapping = {
            "self": "self_portrait",
            "self_plus_environment": "portrait_environment",
            "environment_only": "environment_scene",
            "symbolic_mood": "symbolic_scene",
            "object_focus": "object_focus",
        }
        return mapping.get(subject_mode, "self_portrait")

    @staticmethod
    def _resolve_visual_intent_label(purpose: str, tone: list[str], setting: str) -> str:
        tone_text = " ".join(tone[:2]).strip()
        base = purpose.replace("_", " ")
        if tone_text:
            return f"{tone_text} {base}".strip()
        return f"{base} in {setting.replace('_', ' ')}".strip()

    @staticmethod
    def _weighted_choice(weights: dict[str, float], rng: random.Random, *, fallback: str) -> str:
        filtered = {key: float(value) for key, value in (weights or {}).items() if float(value) > 0.0}
        if not filtered:
            return fallback
        total = sum(filtered.values())
        pick = rng.uniform(0.0, total)
        cursor = 0.0
        for key, value in filtered.items():
            cursor += value
            if pick <= cursor:
                return key
        return next(reversed(filtered.keys()))

    @staticmethod
    def _rng(payload: VisualIntentInput) -> random.Random:
        context = payload.self_expression_context or {}
        seed = context.get("selection_seed")
        if seed is None:
            return random.Random()
        try:
            return random.Random(int(seed))
        except Exception:
            return random.Random(str(seed))


visual_intent_composer_service = VisualIntentComposerService()
