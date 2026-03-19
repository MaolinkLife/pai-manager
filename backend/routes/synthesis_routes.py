import base64
from typing import Optional

from fastapi import APIRouter, Body, HTTPException, status

from modules.synthesis.providers.base import ImageProviderError
from modules.synthesis.service import synthesis_service
from modules.synthesis.types import ImageGenerationRequest

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
    }


@router.post("/image/generate")
def generate_image(payload: dict = Body(...)):
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Prompt is required",
        )

    provider = str(payload.get("provider") or "").strip().lower()
    model = str(payload.get("model") or payload.get("model_id") or provider or "").strip().lower()
    aspect_ratio = str(payload.get("aspect_ratio") or payload.get("aspectRatio") or "1:1")
    default_width, default_height = _aspect_to_resolution(aspect_ratio)

    width_raw = payload.get("width", default_width)
    height_raw = payload.get("height", default_height)
    width, height = _normalize_size(width_raw, height_raw)

    steps_raw = payload.get("num_inference_steps", payload.get("numInferenceSteps", 9))
    guidance_raw = payload.get("guidance_scale", payload.get("guidanceScale", 0.0))
    seed_raw: Optional[int] = payload.get("seed")

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

    request = ImageGenerationRequest(
        prompt=prompt,
        provider=provider,
        model=model or None,
        negative_prompt=negative_prompt,
        width=width,
        height=height,
        num_inference_steps=steps,
        guidance_scale=guidance_scale,
        seed=seed_raw,
    )

    try:
        result = synthesis_service.generate_image(request)
    except ImageProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Image generation failed: {exc}",
        ) from exc

    b64 = base64.b64encode(result.image_bytes).decode("ascii")
    return {
        "status": "ok",
        "provider": result.provider,
        "model_id": result.model_id,
        "mime_type": result.mime_type,
        "width": result.width,
        "height": result.height,
        "seed": result.seed,
        "image_base64": b64,
    }
