from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core.decision_layer import decision_layer
from core.instructor import Instructor
from modules.generative import conversation
from modules.generative.manager import generation_manager
from modules.generative.providers.base import ProviderError
from modules.generative.types import GenerateRequest
from modules.synthesis.media_pipeline import MediaPipelineRequest, media_generation_pipeline
from modules.synthesis.providers.base import ImageProviderError
from modules.system.logger import log_console
from modules.system.service import get_active_character_name
from modules.vision.visual_module import VisualModule
from modules.voice import stt as stt_service


router = APIRouter(prefix="/api/sandbox", tags=["Sandbox"])


class SandboxGenerateRequest(BaseModel):
    mode: Literal["text"] = "text"
    provider: str = Field(default="ollama", min_length=1)
    model: str = ""
    system_prompt: str = ""
    user_prompt: str = Field(default="", min_length=1)
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    options: Dict[str, Any] = Field(default_factory=dict)


class SandboxMediaItem(BaseModel):
    id: str | None = None
    name: str = ""
    mimeType: str = ""
    category: str = "other"
    size: int | None = None
    data: str | None = None
    description: str = ""


class SandboxPipelineRequest(BaseModel):
    mode: Literal["direct", "full"] = "direct"
    provider: str = Field(default="ollama", min_length=1)
    model: str = ""
    user_prompt: str = Field(default="", min_length=1)
    system_prompt: str = ""
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    max_tokens: int | None = None
    media: list[SandboxMediaItem] = Field(default_factory=list)
    case_id: str = ""
    options: Dict[str, Any] = Field(default_factory=dict)


class SandboxImagePipelineRequest(SandboxPipelineRequest):
    mode: Literal["image"] = "image"
    image_provider: str = Field(default="core", min_length=1)
    image_model: str = ""
    image_negative_prompt: str = ""
    width: int = 768
    height: int = 768
    num_inference_steps: int = 30
    guidance_scale: float = 7.0
    seed: int | None = None
    sampler: str | None = None
    scheduler: str | None = "euler"
    comfyui_checkpoint: str | None = None
    use_unified_router: bool | None = None
    use_prompt_builder: bool = True
    image_prompt_policy: str = ""
    image_style_prompt: str = ""
    persist_output: bool = False


class SandboxVisionRequest(SandboxPipelineRequest):
    mode: Literal["vision"] = "vision"


SANDBOX_CASES = [
    {
        "id": "basic_dialogue",
        "title": "Базовый диалог",
        "prompt": "Привет. Как ты себя чувствуешь?",
        "requires": [],
    },
    {
        "id": "memory_probe",
        "title": "Проверка памяти",
        "prompt": "Помнишь, о чем мы говорили в прошлый раз?",
        "requires": ["memory"],
    },
    {
        "id": "image_generation",
        "title": "Генерация изображения",
        "prompt": "Давай создадим арт с персонажем в вечернем парке.",
        "requires": ["image_generation"],
    },
    {
        "id": "screen_vision",
        "title": "Зрение / экран",
        "prompt": "Видишь, что на экране?",
        "requires": ["vision"],
    },
    {
        "id": "image_attachment",
        "title": "Картинка во входе",
        "prompt": "Посмотри на эту картинку и скажи, что видишь.",
        "requires": ["image_attachment", "vision"],
    },
    {
        "id": "voice_transcript",
        "title": "Voice -> text -> pipeline",
        "prompt": "Текст появится после транскрибации wav/mp3 файла.",
        "requires": ["audio_upload", "stt"],
    },
]


@router.post("/generate")
def generate_sandbox(payload: SandboxGenerateRequest):
    if payload.mode != "text":
        raise HTTPException(status_code=400, detail="Only text sandbox mode is available in this endpoint.")

    provider_name = payload.provider.strip().lower()
    provider = generation_manager._providers.get(provider_name)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")

    messages: list[dict[str, str]] = []
    if payload.system_prompt.strip():
        messages.append({"role": "system", "content": payload.system_prompt.strip()})
    messages.append({"role": "user", "content": payload.user_prompt})

    options = dict(payload.options or {})
    if payload.temperature is not None:
        options["temperature"] = payload.temperature
    if payload.top_p is not None:
        options["top_p"] = payload.top_p
    if payload.top_k is not None:
        options["top_k"] = payload.top_k
    if payload.max_tokens is not None:
        options["max_tokens"] = payload.max_tokens
        options["num_predict"] = payload.max_tokens

    metadata = {"source": "sandbox"}
    if payload.model.strip():
        metadata["model"] = payload.model.strip()

    started = time.perf_counter()
    log_console(
        "Sandbox",
        "Запуск одноразовой генерации.",
        {"provider": provider_name, "model": metadata.get("model")},
    )
    try:
        result = provider.generate(
            GenerateRequest(
                messages=messages,
                options=options,
                metadata=metadata,
            )
        )
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "status": "ok",
        "provider": result.provider,
        "model": result.metadata.get("model") or metadata.get("model"),
        "content": result.content,
        "reasoning": result.reasoning,
        "metadata": result.metadata,
        "tool_calls": result.tool_calls,
        "elapsed_ms": elapsed_ms,
    }


@router.get("/cases")
def list_sandbox_cases():
    return {"status": "ok", "cases": SANDBOX_CASES}


def _sandbox_options(payload: SandboxPipelineRequest) -> Dict[str, Any]:
    options = dict(payload.options or {})
    if payload.temperature is not None:
        options["temperature"] = payload.temperature
    if payload.top_p is not None:
        options["top_p"] = payload.top_p
    if payload.top_k is not None:
        options["top_k"] = payload.top_k
    if payload.max_tokens is not None:
        options["max_tokens"] = payload.max_tokens
        options["num_predict"] = payload.max_tokens
    return options


def _usage_from_raw(raw: Any) -> Dict[str, Any]:
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


@router.post("/pipeline-test")
async def run_pipeline_test(payload: SandboxPipelineRequest):
    traces: list[dict[str, Any]] = []

    async def trace_hook(event: dict):
        traces.append(
            {
                "stage": event.get("stage"),
                "state": event.get("state"),
                "elapsed_ms": event.get("elapsed_ms"),
                "details": event.get("details"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    started = time.perf_counter()
    provider_name = payload.provider.strip().lower()
    provider = generation_manager._providers.get(provider_name)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")

    options = _sandbox_options(payload)
    metadata = {"source": "sandbox_pipeline", "mode": payload.mode}
    if payload.model.strip():
        metadata["model"] = payload.model.strip()

    media = [item.model_dump(exclude_none=True) for item in payload.media]
    user_message = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": payload.user_prompt,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "media": media,
        "runtime_meta": {
            "transport": {"name": "main_chat"},
            "sandbox": True,
            "case_id": payload.case_id,
        },
    }

    try:
        if payload.mode == "direct":
            await trace_hook({"stage": "pipeline", "state": "start"})
            prompt_started = time.perf_counter()
            await trace_hook({"stage": "prompt", "state": "start"})
            instructor = Instructor()
            system_prompt = payload.system_prompt.strip() or await instructor.build_system_prompt(
                {},
                {},
                {},
                {"current_emotion": "neutral", "intensity": 0.0},
            )
            messages = [{"role": "system", "content": system_prompt}]
            messages.append({"role": "user", "content": payload.user_prompt})
            await trace_hook(
                {
                    "stage": "prompt",
                    "state": "end",
                    "elapsed_ms": round((time.perf_counter() - prompt_started) * 1000, 2),
                    "details": {"mode": "direct", "messages": len(messages)},
                }
            )

            gen_started = time.perf_counter()
            await trace_hook({"stage": "generation", "state": "start"})
            result = provider.generate(
                GenerateRequest(messages=messages, options=options, metadata=metadata)
            )
            usage = _usage_from_raw(result.raw)
            await trace_hook(
                {
                    "stage": "generation",
                    "state": "end",
                    "elapsed_ms": round((time.perf_counter() - gen_started) * 1000, 2),
                    "details": {"provider": result.provider, "model": result.metadata.get("model"), "usage": usage},
                }
            )
            await trace_hook(
                {
                    "stage": "pipeline",
                    "state": "end",
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
                }
            )
            return {
                "status": "ok",
                "mode": payload.mode,
                "provider": result.provider,
                "model": result.metadata.get("model") or metadata.get("model"),
                "content": result.content,
                "reasoning": result.reasoning,
                "media": [],
                "metadata": result.metadata,
                "usage": usage,
                "traces": traces,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
            }

        await trace_hook({"stage": "pipeline", "state": "start"})
        processing_result = await decision_layer.process_message(user_message, trace_hook=trace_hook)
        instructor = Instructor()
        formatted_history = await instructor.format_for_api(
            processing_result["system_prompt"],
            processing_result["user_message"],
            analysis=processing_result.get("analysis"),
            decisions=processing_result.get("decisions"),
            moral_state=processing_result.get("moral_state"),
            memory_context=processing_result.get("memory_context"),
            visual_context=processing_result.get("visual_context"),
            module_tasks=processing_result.get("module_tasks"),
        )
        gen_started = time.perf_counter()
        await trace_hook({"stage": "generation", "state": "start"})
        result_payload = await conversation.generate_standard(
            processing_result,
            formatted_history,
            processing_result["user_message"],
            trace_hook=trace_hook,
            store=False,
            return_full=True,
        )
        await trace_hook(
            {
                "stage": "generation",
                "state": "end",
                "elapsed_ms": round((time.perf_counter() - gen_started) * 1000, 2),
            }
        )
        await trace_hook(
            {
                "stage": "pipeline",
                "state": "end",
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
        return {
            "status": "ok",
            "mode": payload.mode,
            "provider": result_payload.get("provider"),
            "model": result_payload.get("model"),
            "content": result_payload.get("content") or "",
            "reasoning": result_payload.get("reasoning"),
            "media": result_payload.get("media") or [],
            "metadata": {"module_tasks": processing_result.get("module_tasks") or []},
            "usage": {},
            "traces": traces,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/image-pipeline")
async def run_image_pipeline(payload: SandboxImagePipelineRequest):
    try:
        result = await media_generation_pipeline.run_image(
            MediaPipelineRequest(
                mode="sandbox_forced",
                prompt=payload.user_prompt,
                scenario_key="sandbox",
                negative_prompt=payload.image_negative_prompt,
                llm_provider=payload.provider,
                llm_model=payload.model,
                llm_options=_sandbox_options(payload),
                system_prompt=payload.system_prompt,
                image_provider=payload.image_provider,
                image_model=payload.image_model.strip() or None,
                width=payload.width,
                height=payload.height,
                num_inference_steps=payload.num_inference_steps,
                guidance_scale=payload.guidance_scale,
                seed=payload.seed,
                sampler=payload.sampler,
                scheduler=payload.scheduler,
                comfyui_checkpoint=payload.comfyui_checkpoint,
                use_unified_router=payload.use_unified_router,
                use_prompt_builder=bool(payload.use_prompt_builder),
                prompt_policy=payload.image_prompt_policy,
                style_prompt=payload.image_style_prompt,
                review_generated_image=True,
                persist_output=bool(payload.persist_output),
                source="sandbox_image_pipeline",
                character_name=get_active_character_name(default="PAI"),
                metadata={"case_id": payload.case_id, "allow_scenario_controls": False},
            )
        )
        return {
            "status": "ok",
            "mode": "image",
            "provider": result.provider,
            "model": result.model,
            "content": result.content,
            "reasoning": "",
            "media": result.media,
            "mime_type": result.mime_type,
            "image_base64": result.image_base64,
            "image_prompt": result.image_prompt,
            "negative_prompt": result.negative_prompt,
            "image_parameters": result.image_parameters,
            "vision_description": result.vision_description,
            "metadata": result.metadata,
            "usage": result.usage,
            "traces": result.traces,
            "elapsed_ms": result.elapsed_ms,
        }
    except ImageProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/vision")
async def run_vision_pipeline(payload: SandboxVisionRequest):
    traces: list[dict[str, Any]] = []

    async def trace_hook(event: dict):
        traces.append(
            {
                "stage": event.get("stage"),
                "state": event.get("state"),
                "elapsed_ms": event.get("elapsed_ms"),
                "details": event.get("details"),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )

    started = time.perf_counter()
    provider_name = payload.provider.strip().lower()
    provider = generation_manager._providers.get(provider_name)
    if provider is None:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider_name}")

    options = _sandbox_options(payload)
    metadata = {"source": "sandbox_vision", "mode": "vision"}
    if payload.model.strip():
        metadata["model"] = payload.model.strip()

    media = [item.model_dump(exclude_none=True) for item in payload.media]
    try:
        await trace_hook({"stage": "vision", "state": "start", "details": {"media_count": len(media)}})
        vision_started = time.perf_counter()
        visual = VisualModule()
        described = visual.describe_media_attachments(media) if media else {}
        items = list((described or {}).get("items") or [])
        if not items and not media:
            snapshot = visual.describe_screen_snapshot()
            if snapshot and snapshot.get("description"):
                items = [
                    {
                        "index": 0,
                        "description": str(snapshot.get("description") or ""),
                        "model": snapshot.get("model"),
                        "status": "success",
                    }
                ]
        vision_description = "\n\n".join(
            str(item.get("description") or "").strip()
            for item in items
            if str(item.get("description") or "").strip()
        )
        await trace_hook(
            {
                "stage": "vision",
                "state": "end",
                "elapsed_ms": round((time.perf_counter() - vision_started) * 1000, 2),
                "details": {
                    "items": len(items),
                    "provider": getattr(visual, "provider_name", ""),
                },
            }
        )
        if not vision_description:
            raise HTTPException(status_code=400, detail="Vision produced no description. Check vision provider and input image.")

        gen_started = time.perf_counter()
        await trace_hook({"stage": "vision_answer", "state": "start"})
        system_prompt = payload.system_prompt.strip() or (
            "You answer sandbox vision requests. Use only the supplied vision description as visual grounding. "
            "Do not generate or request a new image."
        )
        result = provider.generate(
            GenerateRequest(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": (
                            f"User request: {payload.user_prompt}\n\n"
                            f"Vision description:\n{vision_description}"
                        ),
                    },
                ],
                options=options,
                metadata=metadata,
            )
        )
        usage = _usage_from_raw(result.raw)
        await trace_hook(
            {
                "stage": "vision_answer",
                "state": "end",
                "elapsed_ms": round((time.perf_counter() - gen_started) * 1000, 2),
                "details": {
                    "provider": result.provider,
                    "model": result.metadata.get("model") or metadata.get("model"),
                    "usage": usage,
                },
            }
        )
        return {
            "status": "ok",
            "mode": "vision",
            "provider": result.provider,
            "model": result.metadata.get("model") or metadata.get("model"),
            "content": result.content,
            "reasoning": result.reasoning,
            "media": [],
            "metadata": {
                **dict(result.metadata or {}),
                "vision_items": items,
                "vision_prompt": (described or {}).get("prompt"),
            },
            "vision_description": vision_description,
            "usage": usage,
            "traces": traces,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except HTTPException:
        raise
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/transcribe")
async def transcribe_audio_file(file: UploadFile = File(...)):
    suffix = Path(file.filename or "audio.wav").suffix.lower()
    if suffix not in {".wav", ".mp3", ".flac", ".ogg", ".m4a"}:
        raise HTTPException(status_code=400, detail="Unsupported audio format")
    import tempfile

    started = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        transcript = stt_service.transcribe_audio(tmp_path)
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
    return {
        "status": "ok",
        "filename": file.filename,
        "transcript": transcript,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
    }
