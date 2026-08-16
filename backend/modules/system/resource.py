from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from constants.paths import (
    DIFFUSER_MODELS_DIR,
    GENERATION_MODELS_DIR,
    GGUF_MODELS_DIR,
    IMAGE_GEN_MODELS_DIR,
    IMAGE_GENERATION_MODELS_DIR,
    MODELS_DIR,
    RVC_MODELS_DIR,
    STT_MODELS_DIR,
    TTS_MODELS_DIR,
    VISION_MODELS_DIR,
)
from utils.audio_devices import (
    get_output_devices,
    get_windows_output_candidates,
    get_device_name_by_id,
    get_input_devices,
)

CHECKPOINT_EXTENSIONS = {
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".bin",
    ".onnx",
}
GGUF_EXTENSIONS = {".gguf"}
RVC_EXTENSIONS = {".pth", ".index"}


def _safe_relpath(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except Exception:
        return path.as_posix()


def _scan_model_files(
    root_dir: str,
    *,
    file_extensions: set[str],
    source: str,
    limit: int,
) -> list[dict[str, Any]]:
    root = Path(root_dir)
    if not root.exists() or not root.is_dir():
        return []

    items: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if len(items) >= limit:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in file_extensions:
            continue
        rel_path = _safe_relpath(path, root)
        items.append(
            {
                "id": rel_path,
                "name": path.stem,
                "path": rel_path,
                "absolute_path": str(path.resolve()),
                "source": source,
                "size_bytes": path.stat().st_size,
            }
        )
    return items


def _scan_diffusers_models(root_dir: str, *, source: str, limit: int) -> list[dict[str, Any]]:
    root = Path(root_dir)
    if not root.exists() or not root.is_dir():
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for marker in root.rglob("model_index.json"):
        if len(items) >= limit:
            break
        if not marker.is_file():
            continue
        model_dir = marker.parent
        rel_path = _safe_relpath(model_dir, root)
        if rel_path in seen:
            continue
        seen.add(rel_path)
        items.append(
            {
                "id": rel_path,
                "name": model_dir.name,
                "path": rel_path,
                "absolute_path": str(model_dir.resolve()),
                "source": source,
                "type": "diffusers_pipeline",
            }
        )
    return items


def list_local_model_resources(limit_per_group: int = 300) -> dict[str, Any]:
    limit = max(1, int(limit_per_group or 300))

    gguf_models = _scan_model_files(
        GGUF_MODELS_DIR,
        file_extensions=GGUF_EXTENSIONS,
        source="local.gguf",
        limit=limit,
    )
    diffusers_models = _scan_diffusers_models(
        DIFFUSER_MODELS_DIR,
        source="local.diffusers",
        limit=limit,
    )
    generation_models = _scan_model_files(
        GENERATION_MODELS_DIR,
        file_extensions=CHECKPOINT_EXTENSIONS,
        source="local.generation",
        limit=limit,
    )
    vision_models = _scan_model_files(
        VISION_MODELS_DIR,
        file_extensions=CHECKPOINT_EXTENSIONS,
        source="local.vision",
        limit=limit,
    )
    tts_models = _scan_model_files(
        TTS_MODELS_DIR,
        file_extensions=CHECKPOINT_EXTENSIONS,
        source="local.tts",
        limit=limit,
    )
    stt_models = _scan_model_files(
        STT_MODELS_DIR,
        file_extensions=CHECKPOINT_EXTENSIONS,
        source="local.stt",
        limit=limit,
    )
    rvc_models = _scan_model_files(
        RVC_MODELS_DIR,
        file_extensions=RVC_EXTENSIONS,
        source="local.rvc",
        limit=limit,
    )
    image_generation_models = _scan_model_files(
        IMAGE_GENERATION_MODELS_DIR,
        file_extensions=CHECKPOINT_EXTENSIONS | GGUF_EXTENSIONS,
        source="local.image_generation",
        limit=limit,
    )
    # Legacy imageGen* roots: keep their contents visible so the hub can
    # surface (and let the user clean up) files left by older versions.
    image_generation_legacy = _scan_model_files(
        IMAGE_GEN_MODELS_DIR,
        file_extensions=CHECKPOINT_EXTENSIONS | GGUF_EXTENSIONS,
        source="local.image_generation_legacy",
        limit=limit,
    ) + _scan_model_files(
        os.path.join(MODELS_DIR, "imageGenerator"),
        file_extensions=CHECKPOINT_EXTENSIONS | GGUF_EXTENSIONS,
        source="local.image_generation_legacy",
        limit=limit,
    )

    groups = {
        "gguf": gguf_models,
        "diffusers": diffusers_models,
        "generation": generation_models,
        "vision": vision_models,
        "tts": tts_models,
        "stt": stt_models,
        "rvc": rvc_models,
        "image_generation": image_generation_models,
        "image_generation_legacy": image_generation_legacy,
    }

    total_count = sum(len(value) for value in groups.values())
    dirs = {
        "models_root": MODELS_DIR,
        "gguf": GGUF_MODELS_DIR,
        "diffusers": DIFFUSER_MODELS_DIR,
        "generation": GENERATION_MODELS_DIR,
        "vision": VISION_MODELS_DIR,
        "tts": TTS_MODELS_DIR,
        "stt": STT_MODELS_DIR,
        "rvc": RVC_MODELS_DIR,
    }

    return {
        "status": "ok",
        "groups": groups,
        "counts": {key: len(value) for key, value in groups.items()},
        "total_count": total_count,
        "limit_per_group": limit,
        "directories": {
            key: {"path": value, "exists": os.path.isdir(value)} for key, value in dirs.items()
        },
    }


def delete_local_model_file(absolute_path: str) -> dict[str, Any]:
    """Delete a model file from local storage.

    The path must resolve inside ``storage/models`` — anything else is
    rejected. Empty parent directories are pruned up to the models root so
    nested layouts (sherpa/STT) don't leave husks behind.
    """
    raw = str(absolute_path or "").strip()
    if not raw:
        return {"status": "error", "message": "path is required"}

    models_root = Path(MODELS_DIR).resolve()
    try:
        target = Path(raw).resolve()
    except Exception:
        return {"status": "error", "message": "Invalid path"}

    if models_root not in target.parents:
        return {"status": "error", "message": "Path is outside the models storage"}
    if not target.is_file():
        return {"status": "error", "message": "File not found"}

    try:
        target.unlink()
        parent = target.parent
        while parent != models_root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    except Exception as exc:
        return {"status": "error", "message": f"Failed to delete: {exc}"}

    return {"status": "ok", "deleted": str(target)}


def get_audio_resources():
    try:
        return {
            "status": "success",
            "all_devices": get_output_devices(),
            "get_windows_output": get_windows_output_candidates(),
            "recording_devices": get_input_devices(),
            "message": "Audio resources retrieved successfully",
        }
    except Exception as exc:
        return {
            "status": "error",
            "content": f"Error while getting audio resources: {str(exc)}",
            "all_devices": [],
            "get_windows_output": [],
            "recording_devices": [],
        }


def get_audio_device_name(device_id):
    return get_device_name_by_id(device_id)
