from __future__ import annotations

import base64
import json
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Literal, Optional

from constants.prompts import (
    MEDIA_IMAGE_PROMPT_BUILDER_SYSTEM_PROMPT,
    MEDIA_IMAGE_PROMPT_BUILDER_USER_TEMPLATE,
)
from modules.generative.manager import generation_manager
from modules.generative.providers.base import ProviderError
from modules.generative.types import GenerateRequest
from modules.synthesis.service import synthesis_service
from modules.synthesis.types import ImageGenerationRequest
from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.runtime_profile import should_release_resources
from modules.system.service import get_active_character_name
from modules.visual_profile_store import visual_profile_store_service
from modules.vision.visual_module import VisualModule

TraceHook = Callable[[dict], Awaitable[None]]


@dataclass
class MediaPipelineRequest:
    mode: Literal["direct", "sandbox_forced", "chat_auto"] = "direct"
    prompt: str = ""
    scenario_key: str = ""
    negative_prompt: str = ""
    llm_provider: str = "ollama"
    llm_model: str = ""
    llm_options: dict[str, Any] = field(default_factory=dict)
    system_prompt: str = ""
    image_provider: str = "diffusers"
    image_model: str | None = None
    width: int = 1024
    height: int = 1024
    num_inference_steps: int = 9
    guidance_scale: float = 0.0
    seed: int | None = None
    sampler: str | None = None
    scheduler: str | None = None
    comfyui_checkpoint: str | None = None
    use_unified_router: bool | None = None
    use_prompt_builder: bool = False
    prompt_policy: str = ""
    style_prompt: str = ""
    review_generated_image: bool = False
    use_visual_intent: bool = False
    persist_output: bool = False
    source: str = "media_pipeline"
    character_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MediaPipelineResult:
    provider: str
    model: str | None
    content: str
    media: list[dict[str, Any]]
    image_bytes: bytes
    mime_type: str
    image_base64: str
    image_prompt: str
    negative_prompt: str
    image_parameters: dict[str, Any]
    vision_description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    traces: list[dict[str, Any]] = field(default_factory=list)
    elapsed_ms: float = 0.0


def _usage_from_raw(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("usage"), dict):
        return dict(raw.get("usage") or {})
    keys = (
        "total_duration",
        "prompt_eval_count",
        "eval_count",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    )
    return {key: raw.get(key) for key in keys if key in raw}


def _strip_markdown_json(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return raw
    if "```json" in raw:
        return raw.split("```json", 1)[1].split("```", 1)[0].strip()
    if raw.startswith("```"):
        return raw.split("```", 1)[1].split("```", 1)[0].strip()
    return raw


def _parse_json_object(text: str) -> dict[str, Any]:
    raw = _strip_markdown_json(text)
    if not raw:
        return {}
    candidates = [raw]
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw[start : end + 1].strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _tool_messages_to_prompt_block(tool_messages: list[dict[str, str]]) -> str:
    lines = ["toolName | content"]
    for item in tool_messages:
        name = str(item.get("name") or "tool").strip()
        content = str(item.get("content") or "").strip().replace("\r\n", "\n")
        lines.append(f"{name} | {content}")
    return "\n".join(lines)


def _time_context_to_visual_cues(value: str) -> str:
    raw = str(value or "").strip().lower()
    match = re.search(r"(\d{1,2}):(\d{2})", raw)
    hour = int(match.group(1)) if match else None
    if hour is None:
        return "natural ambient light, present-moment atmosphere"
    if 5 <= hour < 11:
        return "fresh morning light, soft cool shadows, quiet start-of-day atmosphere"
    if 11 <= hour < 17:
        return "clear daytime light, bright room ambience, crisp natural colors"
    if 17 <= hour < 22:
        return "warm evening light, soft lamp glow, gentle dusk atmosphere"
    return "late-night ambience, screen glow, deep shadows, intimate quiet mood"


def _emotion_context_to_visual_cues(value: str) -> str:
    raw = str(value or "").strip().lower()
    mapping = [
        (("playful", "игрив", "teasing", "сарказ", "вредн"), "playful teasing expression, lively eyes, mischievous body language"),
        (("excited", "joy", "pride", "возбужд", "энерг", "радост", "горд"), "energized mood, bright eyes, animated pose, vivid warm accents"),
        (("sad", "sadness", "longing", "груст", "melanch", "тоск", "печаль"), "quiet melancholic mood, softened gaze, gentle posture, muted emotional lighting"),
        (("angry", "frustration", "resentment", "зл", "irritat", "раздраж", "обид"), "irritated sharp gaze, tense posture, dramatic contrast lighting"),
        (("anxiety", "confusion", "трев", "растер"), "careful uncertain mood, searching gaze, restrained posture"),
        (("tired", "устал", "сонн"), "tired intimate mood, relaxed shoulders, low warm light, cozy stillness"),
        (("seductive", "sensual", "tenderness", "нежн", "ласк"), "soft sensual confidence, warm gaze, elegant relaxed pose"),
        (("neutral", "peace", "calm", "спокой", "умир"), "calm attentive mood, natural expression, relaxed posture"),
    ]
    for markers, cue in mapping:
        if any(marker in raw for marker in markers):
            return cue
    return "expressive mood matching the character's current emotional state"


def _outfit_context_to_visual_cues(value: str, intent: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "a tasteful outfit chosen for the scene"
    lower_intent = str(intent or "").lower()
    if any(marker in lower_intent for marker in ("парк", "park", "улиц", "street", "walk", "гуля")):
        return "stylish casual outdoor outfit adapted from her usual dark wardrobe"
    if any(marker in lower_intent for marker in ("дом", "home", "cozy", "сейчас", "what are you doing")):
        return "comfortable homewear with a few stylish personal details"
    return "a scene-appropriate outfit inspired by her usual style"


def _fallback_image_prompt_from_tools(tool_messages: list[dict[str, str]]) -> str:
    data = {
        str(item.get("name") or "").strip(): str(item.get("content") or "").strip()
        for item in tool_messages
    }
    appearance = data.get("systemAppearance") or "adult woman with distinctive character design"
    outfit = data.get("systemOutfit") or "character outfit matching the current mood"
    clock = data.get("systemClock") or "current moment"
    mood = data.get("emotionMood") or "expressive emotional state"
    intent = data.get("intent") or "share the feeling of the moment"
    time_cues = _time_context_to_visual_cues(clock)
    mood_cues = _emotion_context_to_visual_cues(mood)
    outfit_cues = _outfit_context_to_visual_cues(outfit, intent)
    lower_intent = intent.lower()
    if any(marker in lower_intent for marker in ("что ты сейчас делаешь", "что ты сейчас", "what are you doing", "сейчас делаешь", "сейчас", "right now")):
        activity = "relaxing at a softly lit desk, half-turned toward the viewer, warm cup of tea and glowing screen nearby"
    elif any(marker in lower_intent for marker in ("вечер", "evening", "парк", "park")):
        activity = "walking through an evening park under warm lamps, pausing with a playful glance toward the viewer"
    else:
        activity = "sharing a spontaneous personal moment with a natural expressive pose"
    return (
        f"Masterpiece digital painting of {appearance}, wearing {outfit_cues}, "
        f"{activity}, {time_cues}, {mood_cues}. "
        "Elegant composition, detailed face, vivid color harmony, "
        "soft depth of field, polished illustration, high detail, natural anatomy, beautiful environment, no text."
    )


def _prompt_contains_raw_system_context(prompt: str) -> bool:
    raw = str(prompt or "").lower()
    markers = (
        "current local date",
        "current local time",
        "current emotional state",
        "time context:",
        "emotional direction:",
        "systemclock",
        "emotionmood",
        "toolname",
    )
    return any(marker in raw for marker in markers)


def _normalize_image_size(width: int, height: int) -> tuple[int, int]:
    w = max(256, min(2048, int(width or 768)))
    h = max(256, min(2048, int(height or 768)))
    return (w // 8) * 8, (h // 8) * 8


def _resolve_auto_image_route(request: MediaPipelineRequest) -> tuple[str, str | None, str | None]:
    provider = str(request.image_provider or "").strip().lower()
    model = request.image_model
    checkpoint = request.comfyui_checkpoint
    if provider and provider != "auto":
        return provider, model, checkpoint

    active_provider = str(
        config_service.get_config_value("synthesis.active_provider", "") or ""
    ).strip().lower()
    if active_provider in {"core", "comfyui", "stable_diffusion_webui", "sd_webui", "diffusers"}:
        if active_provider == "comfyui":
            return (
                "comfyui",
                "comfyui_txt2img",
                checkpoint or str(config_service.get_config_value("synthesis.comfyui.default_model", "") or "").strip() or None,
            )
        if active_provider in {"stable_diffusion_webui", "sd_webui"}:
            return "stable_diffusion_webui", "stable_diffusion_webui", checkpoint
        default_model = str(
            request.image_model
            or config_service.get_config_value("synthesis.diffusers.default_model", "")
            or "z_image_turbo"
        ).strip()
        return ("core" if active_provider == "core" else "diffusers"), default_model or None, checkpoint

    if bool(config_service.get_config_value("synthesis.comfyui.enabled", False)):
        return (
            "comfyui",
            "comfyui_txt2img",
            checkpoint or str(config_service.get_config_value("synthesis.comfyui.default_model", "") or "").strip() or None,
        )
    if bool(config_service.get_config_value("synthesis.sd_webui.enabled", False)):
        return "stable_diffusion_webui", "stable_diffusion_webui", checkpoint

    default_model = str(
        request.image_model
        or config_service.get_config_value("synthesis.diffusers.default_model", "")
        or "z_image_turbo"
    ).strip()
    return "core", default_model or None, checkpoint


def _resolve_generation_params(request: MediaPipelineRequest, provider: str) -> dict[str, Any]:
    if provider != "comfyui":
        diffusers_cfg = config_service.get_config_value("synthesis.diffusers", {}) or {}
        return {
            "width": request.width or int(diffusers_cfg.get("width", 1024) or 1024),
            "height": request.height or int(diffusers_cfg.get("height", 1024) or 1024),
            "steps": request.num_inference_steps or int(diffusers_cfg.get("steps", 30) or 30),
            "cfg": request.guidance_scale if request.guidance_scale is not None else float(diffusers_cfg.get("cfg", 7.0) or 7.0),
            "sampler": request.sampler or str(diffusers_cfg.get("sampler", "euler") or "euler"),
            "scheduler": request.scheduler or str(diffusers_cfg.get("scheduler", "normal") or "normal"),
        }

    return {
        "width": request.width or int(config_service.get_config_value("synthesis.comfyui.width", 1024) or 1024),
        "height": request.height or int(config_service.get_config_value("synthesis.comfyui.height", 1024) or 1024),
        "steps": request.num_inference_steps or int(config_service.get_config_value("synthesis.comfyui.steps", 30) or 30),
        "cfg": request.guidance_scale if request.guidance_scale is not None else float(config_service.get_config_value("synthesis.comfyui.cfg", 7.0) or 7.0),
        "sampler": request.sampler or str(config_service.get_config_value("synthesis.comfyui.sampler", "euler") or "euler"),
        "scheduler": request.scheduler or str(config_service.get_config_value("synthesis.comfyui.scheduler", "normal") or "normal"),
    }


def _image_prompt_tool_messages(intent: str, character_name: str | None = None) -> list[dict[str, str]]:
    try:
        profile = visual_profile_store_service.load_profile(character_name=character_name)
        appearance = str(profile.appearance_textarea or "").strip()
        outfit = str(profile.default_outfit or "").strip()
        environment = str(profile.default_environment or "").strip()
        resolved_character_name = str(profile.character_name or character_name or get_active_character_name(default="PAI") or "PAI").strip()
    except Exception:
        appearance = str(config_service.get_config_value("synthesis.prompting.appearance_prompt", "") or "").strip()
        outfit = ""
        environment = ""
        resolved_character_name = str(character_name or get_active_character_name(default="PAI") or "PAI").strip()

    clean_intent = str(intent or "").strip() or "Create an image that the character would want to show right now."
    messages = [
        {
            "role": "tool",
            "name": "systemAppearance",
            "content": appearance or f"{resolved_character_name}, adult woman, distinctive character appearance",
        },
        {
            "role": "tool",
            "name": "systemClock",
            "content": f"Current local date and time: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        },
        {"role": "tool", "name": "intent", "content": clean_intent},
    ]
    _append_optional_tool_message(messages, name="systemOutfit", content=outfit)
    _append_optional_tool_message(messages, name="systemEnvironment", content=environment)
    if bool(config_service.get_config_value("moral.enabled", False)):
        moral_state = config_service.get_config_value("moral.current_state", {}) or {}
        if not isinstance(moral_state, dict):
            moral_state = {}
        emotion = str(
            moral_state.get("current_emotion")
            or moral_state.get("emotion")
            or config_service.get_config_value("moral.default_emotion", "")
            or ""
        ).strip()
        if emotion:
            intensity = moral_state.get("emotion_intensity", moral_state.get("intensity", None))
            emotion_text = f"Current emotional state: {emotion}"
            if intensity is not None:
                emotion_text += f"; intensity={intensity}"
            messages.insert(-1, {"role": "tool", "name": "emotionMood", "content": emotion_text})
    return messages


def _append_optional_tool_message(messages: list[dict[str, str]], *, name: str, content: str) -> None:
    text = str(content or "").strip()
    if not text:
        return
    messages.append({"role": "tool", "name": name, "content": text})


def _scenario_key_for_request(request: MediaPipelineRequest) -> str:
    key = str(request.scenario_key or "").strip().lower()
    if key:
        return key
    source = str(request.source or "").strip().lower()
    if source.startswith("telegram_image_command"):
        return "telegram_command"
    if source.startswith("telegram_take_photo") or source.startswith("telegram_test_image"):
        return "telegram_tool"
    if source.startswith("main_chat"):
        return "main_chat"
    if source.startswith("sandbox"):
        return "sandbox"
    return ""


def _resolve_image_scenario_config(key: str) -> dict[str, Any]:
    scenario_key = str(key or "").strip()
    if not scenario_key:
        return {}
    prompting = config_service.get_config_value("synthesis.prompting", {}) or {}
    scenarios = prompting.get("scenarios") if isinstance(prompting, dict) else {}
    if not isinstance(scenarios, dict):
        return {}
    raw = scenarios.get(scenario_key)
    if not isinstance(raw, dict):
        raw = scenarios.get(scenario_key.lower())
    if not isinstance(raw, dict):
        return {}
    if raw.get("enabled") is False:
        return {}
    return dict(raw)


def _scenario_text(scenario: dict[str, Any], key: str, current: str | None) -> str:
    raw_current = str(current or "").strip()
    if raw_current:
        return raw_current
    return str(scenario.get(key) or "").strip()


def _scenario_override_text(scenario: dict[str, Any], key: str, current: str | None) -> str:
    if key not in scenario:
        return str(current or "").strip()
    value = str(scenario.get(key) or "").strip()
    return value if value else str(current or "").strip()


def _scenario_bool(scenario: dict[str, Any], key: str, current: bool) -> bool:
    if key not in scenario or scenario.get(key) is None:
        return current
    return bool(scenario.get(key))


def _scenario_number(scenario: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = scenario.get(key)
        if value not in (None, ""):
            return value
    return None


def _apply_image_scenario(request: MediaPipelineRequest) -> tuple[MediaPipelineRequest, str, dict[str, Any]]:
    scenario_key = _scenario_key_for_request(request)
    scenario = _resolve_image_scenario_config(scenario_key)
    if not scenario:
        return request, scenario_key, {}

    controls = bool(request.metadata.get("allow_scenario_controls", False))
    request.prompt_policy = _scenario_text(scenario, "prompt_policy", request.prompt_policy)
    request.style_prompt = _scenario_text(scenario, "style_prompt", request.style_prompt)
    request.system_prompt = _scenario_text(scenario, "system_prompt", request.system_prompt)
    request.negative_prompt = _scenario_text(scenario, "negative_prompt", request.negative_prompt)

    if controls:
        provider = str(scenario.get("image_provider") or "").strip()
        model = str(scenario.get("image_model") or "").strip()
        if provider:
            request.image_provider = provider
        if model:
            request.image_model = model
        request.use_prompt_builder = _scenario_bool(scenario, "use_prompt_builder", request.use_prompt_builder)
        request.review_generated_image = _scenario_bool(scenario, "review_generated_image", request.review_generated_image)
        request.use_visual_intent = _scenario_bool(scenario, "use_visual_intent", request.use_visual_intent)
        request.prompt_policy = _scenario_override_text(scenario, "prompt_policy", request.prompt_policy)
        request.style_prompt = _scenario_override_text(scenario, "style_prompt", request.style_prompt)
        request.system_prompt = _scenario_override_text(scenario, "system_prompt", request.system_prompt)
        request.negative_prompt = _scenario_override_text(scenario, "negative_prompt", request.negative_prompt)
        width = _scenario_number(scenario, "width")
        height = _scenario_number(scenario, "height")
        steps = _scenario_number(scenario, "num_inference_steps", "steps")
        guidance = _scenario_number(scenario, "guidance_scale", "cfg")
        if width is not None:
            request.width = int(width)
        if height is not None:
            request.height = int(height)
        if steps is not None:
            request.num_inference_steps = int(steps)
        if guidance is not None:
            request.guidance_scale = float(guidance)
        request.sampler = _scenario_override_text(scenario, "sampler", request.sampler)
        request.scheduler = _scenario_override_text(scenario, "scheduler", request.scheduler)
        checkpoint = str(scenario.get("comfyui_checkpoint") or "").strip()
        if checkpoint:
            request.comfyui_checkpoint = checkpoint

    return request, scenario_key, scenario


def _direct_vision_enabled(request: MediaPipelineRequest) -> bool:
    if request.use_unified_router is not None:
        return bool(request.use_unified_router)
    if request.llm_provider.strip().lower() != "ollama":
        return False
    active_vision = str(config_service.get_config_value("vision.active_provider", "") or "").strip()
    if active_vision not in {"ollama_vision", "llava"}:
        return False
    return bool(
        config_service.get_config_value(
            f"vision.vision_modules.{active_vision}.use_main_model_context",
            False,
        )
    )


class MediaGenerationPipeline:
    async def run_image(
        self,
        request: MediaPipelineRequest,
        trace_hook: Optional[TraceHook] = None,
    ) -> MediaPipelineResult:
        traces: list[dict[str, Any]] = []
        request, scenario_key, scenario_cfg = _apply_image_scenario(request)

        async def emit(event: dict) -> None:
            normalized = {
                "stage": event.get("stage"),
                "state": event.get("state"),
                "elapsed_ms": event.get("elapsed_ms"),
                "details": event.get("details"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            traces.append(normalized)
            if trace_hook is not None:
                await trace_hook(normalized)

        started = time.perf_counter()
        await emit(
            {
                "stage": "image_pipeline",
                "state": "start",
                "details": {
                    "mode": request.mode,
                    "source": request.source,
                    "scenario": scenario_key,
                    "scenario_applied": bool(scenario_cfg),
                },
            }
        )

        tool_messages: list[dict[str, str]] = []
        prompt_payload: dict[str, Any] = {}
        prompt_raw = ""
        prompt_reasoning_raw = ""
        prompt_usage: dict[str, Any] = {}
        fallback_prompt = ""
        image_prompt = str(request.prompt or "").strip()
        negative_prompt = str(request.negative_prompt or "").strip()
        style_prompt = str(request.style_prompt or "").strip()
        prompt_policy = str(request.prompt_policy or "").strip()

        if request.use_prompt_builder:
            llm_provider_name = request.llm_provider.strip().lower()
            provider = generation_manager._providers.get(llm_provider_name)
            if provider is None:
                raise ProviderError(f"Unknown provider: {llm_provider_name}")

            prompt_started = time.perf_counter()
            await emit({"stage": "image_prompt", "state": "start"})
            prompt_system = str(
                config_service.get_config_value(
                    "synthesis.prompting.image_prompt_builder_system_prompt",
                    MEDIA_IMAGE_PROMPT_BUILDER_SYSTEM_PROMPT,
                )
                or MEDIA_IMAGE_PROMPT_BUILDER_SYSTEM_PROMPT
            )
            tool_messages = _image_prompt_tool_messages(request.prompt, request.character_name)
            _append_optional_tool_message(tool_messages, name="sandboxPromptPolicy", content=prompt_policy)
            _append_optional_tool_message(tool_messages, name="sandboxStylePrompt", content=style_prompt)
            user_template = str(
                config_service.get_config_value(
                    "synthesis.prompting.image_prompt_builder_user_template",
                    MEDIA_IMAGE_PROMPT_BUILDER_USER_TEMPLATE,
                )
                or MEDIA_IMAGE_PROMPT_BUILDER_USER_TEMPLATE
            )
            prompt_user = user_template.format(
                tool_context=_tool_messages_to_prompt_block(tool_messages)
            )
            llm_metadata = {"source": request.source, "mode": f"{request.mode}_image_prompt"}
            if request.llm_model.strip():
                llm_metadata["model"] = request.llm_model.strip()
            try:
                prompt_result = provider.generate(
                    GenerateRequest(
                        messages=[
                            {"role": "system", "content": prompt_system},
                            *tool_messages,
                            {"role": "user", "content": prompt_user},
                        ],
                        options={
                            **dict(request.llm_options or {}),
                            "temperature": min(float((request.llm_options or {}).get("temperature", 0.35) or 0.35), 0.45),
                            "num_predict": 900,
                        },
                        metadata=llm_metadata,
                    )
                )
            finally:
                self._release_llm_provider(provider, stage="image_prompt")
            prompt_raw = str(prompt_result.content or "").strip()
            prompt_reasoning_raw = str(prompt_result.reasoning or "").strip()
            prompt_payload = _parse_json_object(prompt_raw) or _parse_json_object(prompt_reasoning_raw)
            prompt_usage = _usage_from_raw(getattr(prompt_result, "raw", None))
            fallback_prompt = _fallback_image_prompt_from_tools(tool_messages)
            image_prompt = str(
                prompt_payload.get("positive_prompt")
                or prompt_payload.get("positivePrompt")
                or prompt_payload.get("prompt")
                or (prompt_raw if prompt_raw and not prompt_raw.startswith("{") else "")
                or fallback_prompt
            ).strip()
            if image_prompt.strip() == request.prompt.strip() or _prompt_contains_raw_system_context(image_prompt):
                image_prompt = fallback_prompt
            negative_prompt = str(
                prompt_payload.get("negative_prompt")
                or prompt_payload.get("negativePrompt")
                or request.negative_prompt
                or ""
            ).strip()
            await emit(
                {
                    "stage": "image_prompt",
                    "state": "end",
                    "elapsed_ms": round((time.perf_counter() - prompt_started) * 1000, 2),
                    "details": {
                        "provider": prompt_result.provider,
                        "model": prompt_result.metadata.get("model"),
                        "prompt_chars": len(image_prompt),
                        "json_parsed": bool(prompt_payload),
                        "used_fallback": image_prompt == fallback_prompt,
                    },
                }
            )
        else:
            _append_optional_tool_message(tool_messages, name="sandboxPromptPolicy", content=prompt_policy)
            _append_optional_tool_message(tool_messages, name="sandboxStylePrompt", content=style_prompt)

        if style_prompt:
            image_prompt = f"{image_prompt}, {style_prompt}" if image_prompt else style_prompt

        resolved_provider, resolved_model, resolved_checkpoint = _resolve_auto_image_route(request)
        defaults = _resolve_generation_params(request, resolved_provider)
        width, height = _normalize_image_size(defaults["width"], defaults["height"])
        image_params = {
            "provider": resolved_provider,
            "model": resolved_model,
            "width": width,
            "height": height,
            "num_inference_steps": max(1, min(80, int(defaults["steps"] or 30))),
            "guidance_scale": float(defaults["cfg"]),
            "seed": request.seed,
            "sampler": str(defaults["sampler"] or "").strip() or None,
            "scheduler": str(defaults["scheduler"] or "").strip() or None,
            "comfyui_checkpoint": str(resolved_checkpoint or "").strip() or None,
            "use_prompt_engineering": False,
            "allow_fallback": bool(config_service.get_config_value("synthesis.diffusers.allow_comfyui_fallback", True))
            if resolved_provider in {"core", "diffusers"}
            else False,
        }

        generation_started = time.perf_counter()
        await emit({"stage": "image_generation", "state": "start", "details": image_params})
        image_result = synthesis_service.generate_image(
            ImageGenerationRequest(
                prompt=image_prompt,
                negative_prompt=negative_prompt,
                provider=image_params["provider"],
                model=image_params["model"],
                width=width,
                height=height,
                num_inference_steps=image_params["num_inference_steps"],
                guidance_scale=image_params["guidance_scale"],
                seed=image_params["seed"],
                sampler=image_params["sampler"],
                scheduler=image_params["scheduler"],
                comfyui_checkpoint=image_params["comfyui_checkpoint"],
                persist_output=request.persist_output,
                use_prompt_engineering=False,
                allow_fallback=bool(image_params["allow_fallback"]),
                use_visual_intent=request.use_visual_intent,
            )
        )
        encoded_image = base64.b64encode(image_result.image_bytes).decode("ascii")
        image_params.update(
            {
                "resolved_provider": image_result.provider,
                "resolved_model": image_result.model_id,
                "resolved_seed": image_result.seed,
                "output_path": image_result.output_path,
            }
        )
        await emit(
            {
                "stage": "image_generation",
                "state": "end",
                "elapsed_ms": round((time.perf_counter() - generation_started) * 1000, 2),
                "details": {
                    "provider": image_result.provider,
                    "model": image_result.model_id,
                    "bytes": len(image_result.image_bytes),
                },
            }
        )

        generated_media = [
            {
                "id": str(uuid.uuid4()),
                "name": f"{request.source or 'generated'}-image.png",
                "mimeType": image_result.mime_type,
                "category": "image",
                "size": len(image_result.image_bytes),
                "data": encoded_image,
            }
        ]

        final_content = "Image generated."
        vision_description = ""
        needs_image_description = bool(prompt_payload.get("needs_image_description", True)) if prompt_payload else request.review_generated_image
        direct_mode = _direct_vision_enabled(request)
        if request.review_generated_image and needs_image_description:
            review_started = time.perf_counter()
            await emit(
                {
                    "stage": "image_review",
                    "state": "start",
                    "details": {"direct_main_model_context": direct_mode},
                }
            )
            llm_provider_name = request.llm_provider.strip().lower()
            provider = generation_manager._providers.get(llm_provider_name)
            if provider is None:
                raise ProviderError(f"Unknown provider: {llm_provider_name}")
            review_messages = [
                {
                    "role": "system",
                    "content": request.system_prompt.strip()
                    or (
                        "You review generated images for the media pipeline. First describe what is visible, "
                        "then write one short in-character line that could accompany the image. "
                        "Do not say this is a test image."
                    ),
                },
            ]
            if direct_mode and llm_provider_name == "ollama":
                review_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Look at the generated image attached to this message. "
                            "Say whether it matches the original request, and describe the visible result briefly.\n\n"
                            f"Original request: {request.prompt}\n"
                            f"Generation prompt: {image_prompt}"
                        ),
                        "images": [encoded_image],
                    }
                )
            else:
                visual = VisualModule()
                described = visual.describe_media_attachments(generated_media) or {}
                items = list(described.get("items") or [])
                vision_description = str(items[0].get("description") or "").strip() if items else ""
                review_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Review this generated image using the vision description below. "
                            "Say whether it matches the original request, and describe the result briefly.\n\n"
                            f"Original request: {request.prompt}\n"
                            f"Generation prompt: {image_prompt}\n"
                            f"Vision description: {vision_description or '<vision unavailable>'}"
                        ),
                    }
                )
            try:
                review_result = provider.generate(
                    GenerateRequest(
                        messages=review_messages,
                        options={
                            **dict(request.llm_options or {}),
                            "num_predict": min(int((request.llm_options or {}).get("num_predict", 512) or 512), 700),
                        },
                        metadata={"source": request.source, "mode": f"{request.mode}_image_review", "model": request.llm_model or None},
                    )
                )
            finally:
                self._release_llm_provider(provider, stage="image_review")
            final_content = review_result.content
            await emit(
                {
                    "stage": "image_review",
                    "state": "end",
                    "elapsed_ms": round((time.perf_counter() - review_started) * 1000, 2),
                    "details": {
                        "provider": review_result.provider,
                        "model": review_result.metadata.get("model"),
                        "direct_main_model_context": direct_mode and llm_provider_name == "ollama",
                    },
                }
            )
        elif request.review_generated_image:
            final_content = "Image generated. Image description step was not requested by the prompt planner."

        await emit(
            {
                "stage": "image_pipeline",
                "state": "end",
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
        return MediaPipelineResult(
            provider=image_result.provider,
            model=image_result.model_id,
            content=final_content,
            media=generated_media,
            image_bytes=image_result.image_bytes,
            mime_type=image_result.mime_type,
            image_base64=encoded_image,
            image_prompt=image_prompt,
            negative_prompt=negative_prompt,
            image_parameters=image_params,
            vision_description=vision_description,
            metadata={
                **dict(request.metadata or {}),
                "scenario": scenario_key,
                "scenario_applied": bool(scenario_cfg),
                "prompt_planner": prompt_payload,
                "prompt_builder_raw": prompt_raw,
                "prompt_builder_reasoning": prompt_reasoning_raw,
                "prompt_builder_json_parsed": bool(prompt_payload),
                "prompt_builder_used_fallback": bool(fallback_prompt and image_prompt == fallback_prompt),
                "tool_context": tool_messages,
                "direct_main_model_context": direct_mode and request.llm_provider.strip().lower() == "ollama",
                "needs_image_description": needs_image_description,
                "pipeline_mode": request.mode,
            },
            usage=prompt_usage,
            traces=traces,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    @staticmethod
    def _release_llm_provider(provider: Any, *, stage: str) -> None:
        if not should_release_resources("generative"):
            return
        release_fn = getattr(provider, "release_resources", None)
        if not callable(release_fn):
            return
        try:
            release_fn()
            log_audit_entry(
                "media_pipeline_llm_provider_released",
                "[MediaPipeline] LLM provider resources released.",
                AuditStatus.INFO,
                details={"provider": getattr(provider, "name", provider.__class__.__name__), "stage": stage},
            )
        except Exception as exc:
            log_audit_entry(
                "media_pipeline_llm_provider_release_error",
                "[MediaPipeline] LLM provider resource release failed.",
                AuditStatus.WARNING,
                details={"provider": getattr(provider, "name", provider.__class__.__name__), "stage": stage, "error": str(exc)},
            )


media_generation_pipeline = MediaGenerationPipeline()
