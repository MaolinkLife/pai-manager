from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SynthesisModelInfo:
    model_id: str
    label: str
    family: str
    source: str
    installed: bool
    path: Optional[str] = None
    vae_path: Optional[str] = None
    hf_repo_id: Optional[str] = None
    default: bool = False
    defaults: Dict[str, Any] | None = None


@dataclass
class ImageGenerationRequest:
    prompt: str
    provider: str = "z_image_turbo"
    model: Optional[str] = None
    negative_prompt: Optional[str] = None
    width: int = 1024
    height: int = 1024
    num_inference_steps: int = 9
    guidance_scale: float = 0.0
    seed: Optional[int] = None
    sampler: Optional[str] = None
    scheduler: Optional[str] = None
    comfyui_checkpoint: Optional[str] = None
    persist_output: bool = False
    # Optional per-request override. None -> use global config.
    use_prompt_engineering: Optional[bool] = None
    allow_fallback: bool = True
    use_visual_intent: Optional[bool] = None
    visual_intent_input: Optional[Dict[str, Any]] = None
    visual_profile: Optional[Dict[str, Any]] = None


@dataclass
class ImageGenerationResult:
    provider: str
    image_bytes: bytes
    model_id: Optional[str] = None
    mime_type: str = "image/png"
    width: int = 1024
    height: int = 1024
    seed: Optional[int] = None
    output_path: Optional[str] = None
