import re
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request, status

from core import tool_event_bus
from modules.synthesis.media_pipeline import MediaPipelineRequest, media_generation_pipeline
from modules.synthesis.model_registry import (
    CHECKPOINT_EXTENSIONS,
    GGUF_EXTENSIONS,
    image_generation_models_root,
    image_generator_models_root,
)
from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.service import synthesis_service
from modules.system.logger import AuditStatus, log_audit_entry
from modules.system.service import get_active_character_name

router = APIRouter(prefix="/api/synthesis", tags=["Synthesis"])


def _aspect_to_resolution(aspect: str) -> tuple[int, int]:
    value = str(aspect or "1:1").strip()
    if value == "16:9":
        return 1344, 768
    if value == "9:16":
        return 768, 1344
    return 1024, 1024


def _normalize_size(width: int, height: int) -> tuple[int, int]:
    w = max(256, min(2048, int(width)))
    h = max(256, min(2048, int(height)))
    # Diffusion models expect dimensions aligned by 8.
    w = (w // 8) * 8
    h = (h // 8) * 8
    return w, h


def _to_bool(value, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return default


def _request_log_context(
    *,
    provider: str,
    model: str,
    width: int,
    height: int,
    steps: int,
    guidance_scale: float,
    allow_fallback: bool,
    use_prompt_engineering: bool,
) -> dict:
    return {
        "provider": provider,
        "model": model or None,
        "width": width,
        "height": height,
        "num_inference_steps": steps,
        "guidance_scale": guidance_scale,
        "allow_fallback": allow_fallback,
        "use_prompt_engineering": use_prompt_engineering,
    }


def _log_generation_api_error(error: Exception, *, request_context: dict, status_code: int) -> None:
    details = {
        "status_code": status_code,
        "error": str(error),
        "error_type": type(error).__name__,
        "request": request_context,
    }
    print(
        "[Synthesis API] Image generation failed: "
        f"status={status_code}; provider={request_context.get('provider') or '-'}; "
        f"model={request_context.get('model') or '-'}; error={error}"
    )
    log_audit_entry(
        "synthesis_api_image_generate_error",
        "[Synthesis API] Image generation failed.",
        AuditStatus.ERROR if status_code >= 500 else AuditStatus.WARNING,
        details=details,
    )


@router.get("/providers")
def get_synthesis_providers():
    return {
        "status": "ok",
        "image": synthesis_service.get_image_providers(),
    }


@router.get("/models")
def get_synthesis_models(refresh: bool = False):
    models = synthesis_service.dump_models_payload(refresh=refresh)
    return {
        "status": "ok",
        "models": models,
        "default_model": next((model["model_id"] for model in models if model.get("default")), None),
        "local_models_root": image_generation_models_root().as_posix(),
    }


@router.get("/comfyui/status")
def get_comfyui_status():
    try:
        return {"status": "ok", "comfyui": synthesis_service.get_comfyui_status()}
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"ComfyUI status check failed: {exc}",
        ) from exc


def _safe_model_filename(filename: str) -> str:
    source_name = Path(str(filename or "")).name
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(source_name).stem).strip("._-")
    suffix = Path(source_name).suffix.lower()
    if suffix in GGUF_EXTENSIONS:
        raise ValueError("GGUF image diffusion models are not supported by the internal Diffusers provider yet")
    if suffix not in CHECKPOINT_EXTENSIONS:
        raise ValueError("Only .safetensors and .ckpt checkpoints are supported for now")
    return f"{stem or 'checkpoint'}{suffix}"


def _unique_checkpoint_path(filename: str) -> Path:
    checkpoints_root = image_generator_models_root()
    checkpoints_root.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_model_filename(filename)
    candidate = checkpoints_root / safe_name
    index = 2
    while candidate.exists():
        candidate = checkpoints_root / f"{Path(safe_name).stem}_{index}{Path(safe_name).suffix}"
        index += 1
    return candidate


@router.post("/models/import")
async def import_synthesis_model(
    request: Request,
    kind: str = Query("checkpoint"),
    filename: str = Query(..., min_length=1, max_length=255),
):
    normalized_kind = str(kind or "checkpoint").strip().lower()
    if normalized_kind != "checkpoint":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only checkpoint import is supported in the internal generator MVP",
        )
    try:
        file_bytes = await request.body()
        if not file_bytes:
            raise ValueError("Model file is empty")
        target_path = _unique_checkpoint_path(filename)
        target_path.write_bytes(file_bytes)
        synthesis_service.list_models(refresh=True)
        return {
            "status": "ok",
            "kind": normalized_kind,
            "file": {
                "name": target_path.name,
                "path": target_path.relative_to(image_generator_models_root()).as_posix(),
                "storage_root": image_generator_models_root().as_posix(),
                "size_bytes": len(file_bytes),
            },
        }
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Model import failed: {exc}",
        ) from exc


@router.post("/models/import-path")
def import_synthesis_model_from_path(payload: dict = Body(...)):
    source_path = str(payload.get("source_path") or payload.get("sourcePath") or "").strip()
    if not source_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_path is required",
        )
    try:
        model = synthesis_service.import_checkpoint_model(
            source_path=source_path,
            label=str(payload.get("label") or "").strip(),
            family=str(payload.get("family") or "auto").strip(),
            model_id=str(payload.get("model_id") or payload.get("modelId") or "").strip(),
            vae_path=str(payload.get("vae_path") or payload.get("vaePath") or "").strip(),
        )
        item = asdict(model)
        item["provider"] = "core"
        return {
            "status": "ok",
            "model": item,
            "local_models_root": image_generation_models_root().as_posix(),
        }
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Model import failed: {exc}",
        ) from exc


@router.post("/image/generate")
async def generate_image(payload: dict = Body(...)):
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt is required",
        )

    provider = str(payload.get("provider") or "core").strip().lower()
    model = str(payload.get("model") or payload.get("model_id") or "").strip().lower()
    if not model and provider not in {"core", "diffusers", "huggingface", "hf", "stable_diffusion_webui", "comfyui"}:
        # Compatibility with older UI that sent the model id as provider.
        model = provider
        provider = "core"
    aspect_ratio = str(payload.get("aspect_ratio") or payload.get("aspectRatio") or "1:1")
    default_width, default_height = _aspect_to_resolution(aspect_ratio)

    width_raw = payload.get("width", default_width)
    height_raw = payload.get("height", default_height)
    width, height = _normalize_size(width_raw, height_raw)

    steps_raw = payload.get("num_inference_steps", payload.get("numInferenceSteps", 9))
    guidance_raw = payload.get("guidance_scale", payload.get("guidanceScale", 0.0))
    seed_raw: Optional[int] = payload.get("seed")
    sampler = str(payload.get("sampler") or payload.get("sampler_name") or payload.get("samplerName") or "").strip() or None
    scheduler = str(payload.get("scheduler") or "").strip() or None
    comfyui_checkpoint = str(
        payload.get("comfyui_checkpoint")
        or payload.get("comfyuiCheckpoint")
        or payload.get("checkpoint")
        or ""
    ).strip() or None

    try:
        steps = max(1, min(80, int(steps_raw)))
    except Exception:
        steps = 9

    try:
        guidance_scale = float(guidance_raw)
    except Exception:
        guidance_scale = 0.0

    negative_prompt = payload.get("negative_prompt", payload.get("negativePrompt"))
    if negative_prompt is not None:
        negative_prompt = str(negative_prompt)
    # Synthesis screen should default to direct provider generation (no LLM prompt engineering).
    use_prompt_engineering = _to_bool(
        payload.get("use_prompt_engineering", payload.get("usePromptEngineering")),
        default=False,
    )

    allow_fallback = _to_bool(
        payload.get("allow_fallback", payload.get("allowFallback")),
        default=provider in {"core", "diffusers"},
    )
    persist_output = _to_bool(
        payload.get("persist_output", payload.get("persistOutput")),
        default=False,
    )
    request_context = _request_log_context(
        provider=provider,
        model=model,
        width=width,
        height=height,
        steps=steps,
        guidance_scale=guidance_scale,
        allow_fallback=allow_fallback,
        use_prompt_engineering=use_prompt_engineering,
    )

    try:
        result = await media_generation_pipeline.run_image(
            MediaPipelineRequest(
                mode="direct",
                prompt=prompt,
                scenario_key=str(payload.get("scenario_key", payload.get("scenarioKey", "")) or ""),
                negative_prompt=negative_prompt or "",
                image_provider=provider,
                image_model=model or None,
                width=width,
                height=height,
                num_inference_steps=steps,
                guidance_scale=guidance_scale,
                seed=seed_raw,
                sampler=sampler,
                scheduler=scheduler,
                comfyui_checkpoint=comfyui_checkpoint,
                use_prompt_builder=bool(use_prompt_engineering),
                review_generated_image=False,
                use_visual_intent=_to_bool(
                    payload.get("use_visual_intent", payload.get("useVisualIntent")),
                    default=False,
                ),
                persist_output=persist_output,
                source="api_synthesis",
                character_name=get_active_character_name(default="PAI"),
                metadata={"allow_scenario_controls": False},
            )
        )
    except ImageProviderError as exc:
        _log_generation_api_error(
            exc,
            request_context=request_context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        tool_event_bus.emit_tool_event(
            tool_name="image.generate",
            status="error",
            source="api_synthesis",
            content=f"[ERROR]: image generation failed: {exc}",
            runtime_meta={
                "event": "tool_event",
                "tool": {"name": "image.generate", "status": "error"},
                "request": request_context,
            },
            tags=["tool", "image", "error"],
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        _log_generation_api_error(
            exc,
            request_context=request_context,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        tool_event_bus.emit_tool_event(
            tool_name="image.generate",
            status="error",
            source="api_synthesis",
            content=f"[ERROR]: image generation failed: {exc}",
            runtime_meta={
                "event": "tool_event",
                "tool": {"name": "image.generate", "status": "error"},
                "request": request_context,
            },
            tags=["tool", "image", "error"],
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Image generation failed: {exc}",
        ) from exc

    tool_event_bus.emit_tool_event(
        tool_name="image.generate",
        status="ok",
        source="api_synthesis",
        content=(
            "[OK]: image generated successfully. "
            f"provider={result.provider}; model={result.model or '-'}; "
            f"size={result.image_parameters.get('width')}x{result.image_parameters.get('height')}; "
            f"seed={result.image_parameters.get('resolved_seed')}"
        ),
        runtime_meta={
            "event": "tool_event",
            "tool": {"name": "image.generate", "status": "ok"},
            "request": request_context,
            "result": {
                "provider": result.provider,
                "model_id": result.model,
                "width": result.image_parameters.get("width"),
                "height": result.image_parameters.get("height"),
                "seed": result.image_parameters.get("resolved_seed"),
            },
        },
        tags=["tool", "image", "ok"],
    )

    return {
        "status": "ok",
        "provider": result.provider,
        "model_id": result.model,
        "mime_type": result.mime_type,
        "width": result.image_parameters.get("width"),
        "height": result.image_parameters.get("height"),
        "seed": result.image_parameters.get("resolved_seed"),
        "output_path": result.image_parameters.get("output_path"),
        "image_base64": result.image_base64,
        "image_prompt": result.image_prompt,
        "negative_prompt": result.negative_prompt,
        "image_parameters": result.image_parameters,
        "metadata": result.metadata,
        "traces": result.traces,
        "elapsed_ms": result.elapsed_ms,
    }
