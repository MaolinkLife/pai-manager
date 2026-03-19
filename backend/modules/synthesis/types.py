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


@dataclass
class ImageGenerationResult:
    provider: str
    image_bytes: bytes
    model_id: Optional[str] = None
    mime_type: str = "image/png"
    width: int = 1024
    height: int = 1024
    seed: Optional[int] = None
