from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict
from typing import List

from constants.prompts import (
    SYNTHESIS_IMAGE_ASSESSMENT_SYSTEM_PROMPT,
    SYNTHESIS_IMAGE_ASSESSMENT_USER_TEMPLATE,
    SYNTHESIS_PROMPT_ENGINEERING_SYSTEM_PROMPT,
    SYNTHESIS_PROMPT_ENGINEERING_USER_TEMPLATE,
)
from modules.synthesis.model_registry import SynthesisModelRegistry
from modules.synthesis.providers.comfyui import ComfyUIProvider
from modules.synthesis.providers.diffusers_generic import DiffusersGenericProvider
from modules.synthesis.providers.stable_diffusion_webui import StableDiffusionWebUIProvider
from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.types import (
    ImageGenerationRequest,
    ImageGenerationResult,
    SynthesisModelInfo,
)
from modules.generative import generation_manager
from modules.generative.types import GenerateRequest
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.runtime_profile import should_release_resources
from modules.system.service import get_active_character_name, get_config_value
from modules.visual_intent_composer import (
    VisualIntentInput,
    VisualProfile,
    visual_intent_composer_service,
)
from modules.visual_profile_store import visual_profile_store_service
from modules.visual_prompt_builder import visual_prompt_builder_service


class SynthesisService:
    def __init__(self) -> None:
        self._registry = SynthesisModelRegistry()
        self._provider = DiffusersGenericProvider()
        self._sd_webui_provider = StableDiffusionWebUIProvider()
        self._comfyui_provider = ComfyUIProvider()

    def list_models(self, refresh: bool = False) -> List[SynthesisModelInfo]:
        if refresh:
            self._registry.reload()
        return self._registry.list_models()

    def import_checkpoint_model(
        self,
        *,
        source_path: str,
        label: str = "",
        family: str = "auto",
        model_id: str = "",
        vae_path: str = "",
    ) -> SynthesisModelInfo:
        return self._registry.import_checkpoint(
            source_path,
            label=label,
            family=family,
            model_id=model_id,
            vae_path=vae_path,
        )

    def get_image_providers(self) -> list[str]:
        providers = {"core"}
        if any(model.family == "stable-diffusion-webui" for model in self._registry.list_models()):
            providers.add("stable_diffusion_webui")
        if any(model.family == "comfyui" for model in self._registry.list_models()):
            providers.add("comfyui")
        return sorted(providers)

    def get_comfyui_status(self) -> dict:
        return self._comfyui_provider.inspect()

    @staticmethod
    def _provider_name_for_model(model: SynthesisModelInfo) -> str:
        if model.family == "stable-diffusion-webui":
            return "stable_diffusion_webui"
        if model.family == "comfyui":
            return "comfyui"
        return "core"

    @staticmethod
    def _diffusers_capabilities() -> dict:
        try:
            import diffusers
        except Exception as exc:
            return {
                "available": False,
                "version": None,
                "z_image_pipeline": False,
                "error": str(exc),
            }
        return {
            "available": True,
            "version": getattr(diffusers, "__version__", None),
            "z_image_pipeline": hasattr(diffusers, "ZImagePipeline"),
            "error": "",
        }

    def _model_capabilities(self, model: SynthesisModelInfo) -> dict:
        if model.family == "z-image":
            diffusers_capabilities = self._diffusers_capabilities()
            return {
                "provider": "core",
                "required_pipeline": "ZImagePipeline",
                "pipeline_available": bool(diffusers_capabilities.get("z_image_pipeline")),
                "diffusers": diffusers_capabilities,
            }
        if model.family == "stable-diffusion-webui":
            return {
                "provider": "stable_diffusion_webui",
                "required_pipeline": "remote_webui_api",
                "pipeline_available": True,
            }
        if model.family == "comfyui":
            enabled = bool(get_config_value("synthesis.comfyui.enabled", False))
            checkpoint = str(get_config_value("synthesis.comfyui.default_model", "") or "").strip()
            return {
                "provider": "comfyui",
                "required_pipeline": "remote_comfyui_api",
                "pipeline_available": enabled and bool(checkpoint),
                "enabled": enabled,
                "checkpoint_configured": bool(checkpoint),
            }
        if model.family in {"stable-diffusion-checkpoint", "sdxl-checkpoint"}:
            return {
                "provider": "core",
                "required_pipeline": "from_single_file",
                "pipeline_available": bool(self._diffusers_capabilities().get("available")),
            }
        return {
            "provider": "core",
            "required_pipeline": "AutoPipelineForText2Image",
            "pipeline_available": bool(self._diffusers_capabilities().get("available")),
        }

    def _resolve_target_model(self, request: ImageGenerationRequest) -> SynthesisModelInfo:
        provider = (request.provider or "").strip().lower()
        model_id = (request.model or "").strip().lower()
        if provider == "core":
            provider = "diffusers"
        if provider in {"diffusers", "huggingface", "hf", "stable_diffusion_webui", "comfyui"}:
            model_id = model_id or ""
        elif not model_id:
            # Backwards compatibility: old UI/API sent model ids in the provider field.
            model_id = provider
        if not model_id:
            default_model_id = self._registry.get_default_model_id()
            if not default_model_id:
                raise ImageProviderError("No image models are registered.")
            model_id = default_model_id

        model = self._registry.get_model(model_id)
        if model is None:
            available = ", ".join(m.model_id for m in self._registry.list_models())
            raise ImageProviderError(
                f"Unknown image model '{model_id}'. Available: {available}"
            )
        if provider == "comfyui" and model.family != "comfyui":
            comfyui_model = next(
                (candidate for candidate in self._registry.list_models() if candidate.family == "comfyui"),
                None,
            )
            if comfyui_model is None:
                raise ImageProviderError("ComfyUI image model is not registered.")
            return comfyui_model
        if provider == "stable_diffusion_webui" and model.family != "stable-diffusion-webui":
            sd_webui_model = next(
                (candidate for candidate in self._registry.list_models() if candidate.family == "stable-diffusion-webui"),
                None,
            )
            if sd_webui_model is None:
                raise ImageProviderError("Stable Diffusion WebUI image model is not registered.")
            return sd_webui_model
        return model

    def _resolve_fallback_models(
        self,
        primary: SynthesisModelInfo,
    ) -> List[SynthesisModelInfo]:
        fallback_families = {
            "stable-diffusion-webui",
            "comfyui",
            "stable-diffusion",
            "sdxl",
            "diffusion",
        }
        pool = [
            model
            for model in self._registry.list_models()
            if model.model_id != primary.model_id and model.family in fallback_families
        ]
        if not pool:
            return []

        ordered: List[SynthesisModelInfo] = []
        priority_ids = ("stable_diffusion_webui", "stable_diffusion_v1_5")
        for model_id in priority_ids:
            preferred = next((m for m in pool if m.model_id == model_id), None)
            if preferred is not None:
                ordered.append(preferred)

        for candidate in pool:
            if all(existing.model_id != candidate.model_id for existing in ordered):
                ordered.append(candidate)
        return ordered

    @staticmethod
    def _strip_markdown_json(text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return raw
        if "```json" in raw:
            return raw.split("```json", 1)[1].split("```", 1)[0].strip()
        if raw.startswith("```"):
            return raw.split("```", 1)[1].split("```", 1)[0].strip()
        return raw

    @staticmethod
    def _extract_prompt_pair_from_payload(payload: object) -> tuple[str, str]:
        if not isinstance(payload, dict):
            return "", ""
        positive = str(
            payload.get("positivePrompt")
            or payload.get("positive_prompt")
            or payload.get("positive")
            or ""
        ).strip()
        negative = str(
            payload.get("negativePrompt")
            or payload.get("negative_prompt")
            or payload.get("negative")
            or ""
        ).strip()
        return positive, negative

    def _parse_prompt_pair_from_text(self, text: str) -> tuple[str, str]:
        raw = self._strip_markdown_json(text)
        if not raw:
            return "", ""

        candidates: list[str] = [raw]
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            json_slice = raw[start : end + 1].strip()
            if json_slice and json_slice not in candidates:
                candidates.append(json_slice)

        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except Exception:
                continue
            positive, negative = self._extract_prompt_pair_from_payload(payload)
            if positive or negative:
                return positive, negative
        return "", ""

    def _prompting_cfg(self) -> dict:
        cfg = get_config_value("synthesis.prompting", {}) or {}
        return cfg if isinstance(cfg, dict) else {}

    def _resolve_visual_profile(self, request: ImageGenerationRequest) -> VisualProfile:
        request_profile = request.visual_profile if isinstance(request.visual_profile, dict) else {}
        return visual_profile_store_service.load_profile(request_profile=request_profile)

    def _ensure_visual_profile_anchor(self, profile: VisualProfile) -> VisualProfile:
        updated_profile, generated = visual_intent_composer_service.ensure_appearance_anchor(profile)
        if not generated:
            return updated_profile
        try:
            visual_profile_store_service.persist_profile(updated_profile)
            visual_profile_store_service.persist_generated_anchor_if_missing(generated)
        except Exception as exc:
            log_audit_entry(
                "synthesis_visual_profile_persist_failed",
                "[Synthesis] Failed to persist generated visual appearance anchor.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
        return updated_profile

    def _prepare_visual_intent_prompt(
        self,
        request: ImageGenerationRequest,
    ) -> tuple[ImageGenerationRequest, VisualProfile]:
        profile = self._ensure_visual_profile_anchor(self._resolve_visual_profile(request))
        if not bool(request.use_visual_intent) and not isinstance(request.visual_intent_input, dict):
            return request, profile

        try:
            raw_payload = request.visual_intent_input if isinstance(request.visual_intent_input, dict) else {}
            payload = VisualIntentInput.model_validate(
                {
                    **raw_payload,
                    "visual_profile": {
                        **profile.model_dump(),
                        **(raw_payload.get("visual_profile") if isinstance(raw_payload.get("visual_profile"), dict) else {}),
                    },
                }
            )
            plan = visual_intent_composer_service.compose(payload)
            built_prompt, built_negative = visual_prompt_builder_service.build_prompt_pair(
                profile=payload.visual_profile,
                plan=plan,
            )
            log_audit_entry(
                "synthesis_visual_intent_composed",
                "[Synthesis] Visual intent plan composed.",
                AuditStatus.INFO,
                details={
                    "plan": plan.model_dump(),
                    "render_profile": payload.visual_profile.render_profile,
                },
            )
            request.prompt = built_prompt
            if not str(request.negative_prompt or "").strip():
                request.negative_prompt = built_negative
        except Exception as exc:
            log_audit_entry(
                "synthesis_visual_intent_failed",
                "[Synthesis] Visual intent composition failed; fallback to raw prompt.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
        return request, profile

    def _engineer_prompts(
        self,
        *,
        request_prompt: str,
        previous_positive: str,
        previous_negative: str,
        feedback: str,
    ) -> tuple[str, str]:
        cfg = self._prompting_cfg()
        character_name = str(get_active_character_name(default="PAI") or "PAI").strip() or "PAI"
        user_name = str(get_config_value("system.user_name", "User") or "User").strip() or "User"
        visual_profile = self._ensure_visual_profile_anchor(
            VisualProfile.model_validate(
                (cfg.get("visual_profile") if isinstance(cfg.get("visual_profile"), dict) else {})
                or {
                    "character_name": character_name,
                    "appearance_textarea": str(cfg.get("appearance_prompt") or "").strip(),
                }
            )
        )
        appearance_prompt = str(visual_profile.appearance_textarea or "").strip()
        default_negative = str(cfg.get("default_negative_prompt") or "").strip()

        system = SYNTHESIS_PROMPT_ENGINEERING_SYSTEM_PROMPT.format(character_name=visual_profile.character_name or character_name)
        user = SYNTHESIS_PROMPT_ENGINEERING_USER_TEMPLATE.format(
            character_name=visual_profile.character_name or character_name,
            user_name=user_name,
            appearance_prompt=appearance_prompt or "<none>",
            request_prompt=request_prompt or "<none>",
            previous_positive=previous_positive or "<none>",
            previous_negative=previous_negative or "<none>",
            feedback=feedback or "<none>",
        )
        options = {
            "temperature": 0.2,
            "num_predict": 900,
        }
        positive = ""
        negative = ""
        result = None
        try:
            result = generation_manager.generate(
                GenerateRequest(
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    options=options,
                    metadata={"mode": "synthesis_prompt_engineering"},
                )
            )
            content_text = str(getattr(result, "content", "") or "")
            reasoning_text = str(getattr(result, "reasoning", "") or "")
            positive, negative = self._parse_prompt_pair_from_text(content_text)
            if not positive and not negative and reasoning_text:
                positive, negative = self._parse_prompt_pair_from_text(reasoning_text)
            if not positive and not negative:
                log_audit_entry(
                    "synthesis_prompt_engineering_retry",
                    "[Synthesis] Prompt engineering returned no JSON payload; retrying once.",
                    AuditStatus.WARNING,
                    details={
                        "reason": "empty_or_unparseable_payload",
                        "done_reason": (
                            (getattr(result, "raw", {}) or {}).get("done_reason")
                            if isinstance(getattr(result, "raw", None), dict)
                            else None
                        ),
                    },
                )
                retry_options = dict(options)
                retry_options["num_predict"] = 1600
                retry_result = generation_manager.generate(
                    GenerateRequest(
                        messages=[
                            {"role": "system", "content": system},
                            {
                                "role": "user",
                                "content": (
                                    f"{user}\n"
                                    "IMPORTANT: Return ONLY strict JSON object with keys "
                                    "\"positivePrompt\" and \"negativePrompt\"."
                                ),
                            },
                        ],
                        options=retry_options,
                        metadata={"mode": "synthesis_prompt_engineering_retry"},
                    )
                )
                content_text = str(getattr(retry_result, "content", "") or "")
                reasoning_text = str(getattr(retry_result, "reasoning", "") or "")
                positive, negative = self._parse_prompt_pair_from_text(content_text)
                if not positive and not negative and reasoning_text:
                    positive, negative = self._parse_prompt_pair_from_text(reasoning_text)
        except Exception as exc:
            log_audit_entry(
                "synthesis_prompt_engineering_fallback",
                "[Synthesis] Prompt engineering failed; fallback to direct prompt.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )

        if not positive:
            positive = request_prompt.strip()
            if appearance_prompt:
                positive = f"{appearance_prompt}\n\n{positive}".strip()
        if not negative:
            negative = previous_negative.strip() or default_negative
        return positive, negative

    def _assess_image_quality(
        self,
        *,
        image_bytes: bytes,
        target_request: str,
        positive_prompt: str,
    ) -> tuple[float, str]:
        cfg = self._prompting_cfg()
        if not bool(cfg.get("assess_enabled", True)):
            return 1.0, "assessment disabled"
        character_name = str(get_active_character_name(default="PAI") or "PAI").strip() or "PAI"
        user_name = str(get_config_value("system.user_name", "User") or "User").strip() or "User"

        try:
            from modules.vision.visual_module import VisualModule

            vm = VisualModule()
            if not vm.is_ready():
                return 1.0, "vision provider not ready"
            media_payload = [
                {
                    "category": "image",
                    "name": "generated.png",
                    "mimeType": "image/png",
                    "data": base64.b64encode(image_bytes).decode("ascii"),
                }
            ]
            described = vm.describe_media_attachments(media_payload) or {}
            items = list(described.get("items") or [])
            if not items:
                return 1.0, "vision produced no description"
            description = str(items[0].get("description") or "").strip()
            if not description:
                return 1.0, "vision description empty"
        except Exception as exc:
            return 1.0, f"vision unavailable: {exc}"

        system = SYNTHESIS_IMAGE_ASSESSMENT_SYSTEM_PROMPT.format(character_name=character_name)
        user = SYNTHESIS_IMAGE_ASSESSMENT_USER_TEMPLATE.format(
            character_name=character_name,
            user_name=user_name,
            target_request=target_request,
            positive_prompt=positive_prompt,
            description=description,
        )
        result = generation_manager.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                options={"temperature": 0.1, "num_predict": 280},
                metadata={"mode": "synthesis_image_assessment"},
            )
        )
        raw = self._strip_markdown_json(getattr(result, "content", "") or "")
        score = 0.75
        feedback = "minor mismatch"
        satisfied = False
        try:
            payload = json.loads(raw)
            if isinstance(payload, dict):
                score = float(payload.get("score", score))
                feedback = str(payload.get("feedback") or feedback)
                satisfied = bool(payload.get("satisfied", False))
        except Exception:
            pass
        if satisfied and score < 0.9:
            score = 0.9
        if (not satisfied) and score > 0.75:
            score = 0.75
        score = max(0.0, min(1.0, score))
        return score, feedback.strip()

    def _generate_once(
        self,
        *,
        request: ImageGenerationRequest,
        model: SynthesisModelInfo,
        provider_name: str,
    ) -> ImageGenerationResult:
        if model.family == "stable-diffusion-webui":
            return self._sd_webui_provider.generate(request, model)
        if model.family == "comfyui":
            return self._comfyui_provider.generate(request, model)
        try:
            return self._provider.generate(request, model)
        except ImageProviderError as exc:
            log_audit_entry(
                "synthesis_primary_model_failed",
                "[Synthesis] Primary image model failed.",
                AuditStatus.WARNING,
                details={
                    "model_id": model.model_id,
                    "family": model.family,
                    "provider": provider_name,
                    "allow_fallback": bool(request.allow_fallback),
                    "error": str(exc),
                },
            )
            if not request.allow_fallback:
                raise
            fallback_models = self._resolve_fallback_models(model)
            if not fallback_models:
                raise
            last_error = exc
            for fallback_model in fallback_models:
                fallback_provider = self._provider_name_for_model(fallback_model)
                fallback_request = ImageGenerationRequest(
                    prompt=request.prompt,
                    provider=fallback_provider,
                    model=fallback_model.model_id,
                    negative_prompt=request.negative_prompt,
                    width=request.width,
                    height=request.height,
                    num_inference_steps=request.num_inference_steps,
                    guidance_scale=request.guidance_scale,
                    seed=request.seed,
                    sampler=request.sampler,
                    scheduler=request.scheduler,
                    comfyui_checkpoint=request.comfyui_checkpoint,
                    persist_output=request.persist_output,
                    use_prompt_engineering=request.use_prompt_engineering,
                    allow_fallback=False,
                )
                try:
                    log_audit_entry(
                        "synthesis_fallback_attempt",
                        "[Synthesis] Trying fallback image model.",
                        AuditStatus.WARNING,
                        details={
                            "primary_model_id": model.model_id,
                            "fallback_model_id": fallback_model.model_id,
                            "fallback_family": fallback_model.family,
                            "fallback_provider": fallback_provider,
                            "primary_error": str(exc),
                        },
                    )
                    if fallback_model.family == "stable-diffusion-webui":
                        return self._sd_webui_provider.generate(fallback_request, fallback_model)
                    if fallback_model.family == "comfyui":
                        return self._comfyui_provider.generate(fallback_request, fallback_model)
                    return self._provider.generate(fallback_request, fallback_model)
                except ImageProviderError as nested_exc:
                    log_audit_entry(
                        "synthesis_fallback_failed",
                        "[Synthesis] Fallback image model failed.",
                        AuditStatus.WARNING,
                        details={
                            "primary_model_id": model.model_id,
                            "fallback_model_id": fallback_model.model_id,
                            "error": str(nested_exc),
                        },
                    )
                    last_error = nested_exc
                    continue
            raise last_error

    def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        try:
            request, _visual_profile = self._prepare_visual_intent_prompt(request)
            model = self._resolve_target_model(request)
            provider_name = self._provider_name_for_model(model)
            request.provider = provider_name
            request.model = model.model_id

            log_audit_entry(
                "synthesis_generate_image_start",
                "[Synthesis] Start image generation.",
                AuditStatus.INFO,
                details={
                    "provider": provider_name,
                    "model_id": model.model_id,
                    "prompt": request.prompt,
                    "negative_prompt": request.negative_prompt,
                    "width": request.width,
                    "height": request.height,
                    "num_inference_steps": request.num_inference_steps,
                    "guidance_scale": request.guidance_scale,
                    "seed": request.seed,
                    "sampler": request.sampler,
                    "scheduler": request.scheduler,
                    "comfyui_checkpoint": request.comfyui_checkpoint,
                    "use_prompt_engineering": request.use_prompt_engineering,
                    "allow_fallback": request.allow_fallback,
                },
            )
            prompting = self._prompting_cfg()
            prompt_engineering_enabled = (
                bool(request.use_prompt_engineering)
                if request.use_prompt_engineering is not None
                else bool(prompting.get("enabled", True))
            )
            if not prompt_engineering_enabled:
                return self._generate_once(request=request, model=model, provider_name=provider_name)

            retry_enabled = bool(prompting.get("retry_enabled", True))
            max_attempts = int(prompting.get("max_attempts", 3) or 3) if retry_enabled else 1
            max_attempts = max(1, min(max_attempts, 6))
            threshold = float(prompting.get("quality_threshold", 0.72) or 0.72)
            threshold = max(0.0, min(1.0, threshold))

            feedback = ""
            prev_positive = ""
            prev_negative = request.negative_prompt or ""
            last_result: ImageGenerationResult | None = None

            for attempt in range(1, max_attempts + 1):
                positive_prompt, engineered_negative = self._engineer_prompts(
                    request_prompt=request.prompt,
                    previous_positive=prev_positive,
                    previous_negative=prev_negative,
                    feedback=feedback,
                )
                candidate_request = ImageGenerationRequest(
                    prompt=positive_prompt,
                    provider=request.provider,
                    model=request.model,
                    negative_prompt=engineered_negative,
                    width=request.width,
                    height=request.height,
                    num_inference_steps=request.num_inference_steps,
                    guidance_scale=request.guidance_scale,
                    seed=request.seed,
                    sampler=request.sampler,
                    scheduler=request.scheduler,
                    comfyui_checkpoint=request.comfyui_checkpoint,
                    persist_output=request.persist_output,
                    allow_fallback=request.allow_fallback,
                )
                log_audit_entry(
                    "synthesis_prompt_iteration",
                    "[Synthesis] Prompt refinement iteration started.",
                    AuditStatus.INFO,
                    details={
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "provider": candidate_request.provider,
                        "model": candidate_request.model,
                        "negative_prompt_length": len(candidate_request.negative_prompt or ""),
                    },
                )
                result = self._generate_once(
                    request=candidate_request,
                    model=model,
                    provider_name=provider_name,
                )
                last_result = result
                score, assess_feedback = self._assess_image_quality(
                    image_bytes=result.image_bytes,
                    target_request=request.prompt,
                    positive_prompt=positive_prompt,
                )
                log_audit_entry(
                    "synthesis_prompt_iteration_assessed",
                    "[Synthesis] Prompt refinement iteration assessed.",
                    AuditStatus.INFO,
                    details={
                        "attempt": attempt,
                        "score": score,
                        "threshold": threshold,
                        "feedback": assess_feedback[:220],
                    },
                )
                if score >= threshold:
                    return result

                prev_positive = positive_prompt
                prev_negative = engineered_negative
                feedback = assess_feedback or "Improve fidelity to request."

            if last_result is not None:
                return last_result
            raise ImageProviderError("Image generation failed: no result produced.")
        finally:
            if should_release_resources("synthesis"):
                for provider in (self._provider, self._sd_webui_provider, self._comfyui_provider):
                    release_fn = getattr(provider, "release_resources", None)
                    if callable(release_fn):
                        try:
                            release_fn()
                        except Exception as exc:
                            log_audit_entry(
                                "synthesis_provider_release_error",
                                "[Synthesis] Provider resource release failed.",
                                AuditStatus.WARNING,
                                details={"provider": getattr(provider, "name", provider.__class__.__name__), "error": str(exc)},
                            )

    def dump_models_payload(self, refresh: bool = False) -> list[dict]:
        payload = []
        for model in self.list_models(refresh=refresh):
            item = asdict(model)
            item["provider"] = self._provider_name_for_model(model)
            item["capabilities"] = self._model_capabilities(model)
            payload.append(item)
        return payload


synthesis_service = SynthesisService()
