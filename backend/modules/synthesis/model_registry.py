from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from constants.paths import (
    DIFFUSER_MODELS_DIR,
    IMAGE_GEN_DIFFUSER_MODELS_DIR,
    IMAGE_GENERATION_CHECKPOINTS_DIR,
    IMAGE_GENERATION_MODELS_DIR,
    MODELS_DIR,
)
from modules.synthesis.types import SynthesisModelInfo
from modules.system.logger import AuditStatus, log_audit_entry

MODEL_MANIFEST_FILE = "synthesis.model.json"
MODEL_INDEX_FILE = "model_index.json"
CHECKPOINT_EXTENSIONS = {".safetensors", ".ckpt"}
GGUF_EXTENSIONS = {".gguf"}
UNSUPPORTED_IMAGE_MODEL_EXTENSIONS = GGUF_EXTENSIONS


def _to_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _infer_family(folder_name: str, class_name: str = "") -> str:
    folder = (folder_name or "").lower()
    class_norm = (class_name or "").lower()
    probe = f"{folder} {class_norm}"
    if "zimage" in probe or "z-image" in probe:
        return "z-image"
    if "flux" in probe:
        return "flux"
    if "xl" in probe or "sdxl" in probe:
        return "sdxl"
    if "stable" in probe and "diffusion" in probe:
        return "stable-diffusion"
    return "diffusion"


def _safe_model_id(prefix: str, value: str) -> str:
    stem = Path(value).stem.lower()
    safe = re.sub(r"[^a-z0-9._-]+", "_", stem).strip("._-")
    return f"{prefix}_{safe or 'checkpoint'}"


def _safe_slug(value: str, fallback: str = "model") -> str:
    stem = Path(value or fallback).stem.lower()
    safe = re.sub(r"[^a-z0-9._-]+", "_", stem).strip("._-")
    return safe or fallback


def _looks_like_sdxl_checkpoint(value: str) -> bool:
    probe = Path(value or "").stem.lower()
    return "sdxl" in probe or re.search(r"(^|[_.-])xl([_.-]|$)", probe) is not None


def image_generator_models_root() -> Path:
    root = Path(IMAGE_GENERATION_CHECKPOINTS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def image_generation_models_root() -> Path:
    root = Path(IMAGE_GENERATION_MODELS_DIR)
    root.mkdir(parents=True, exist_ok=True)
    return root


def legacy_image_gen_diffuser_models_root() -> Path:
    return Path(IMAGE_GEN_DIFFUSER_MODELS_DIR)


def legacy_image_generator_checkpoints_root() -> Path:
    return Path(MODELS_DIR) / "imageGenerator" / "checkpoints"


class SynthesisModelRegistry:
    def __init__(self) -> None:
        self._root = os.path.join(DIFFUSER_MODELS_DIR, "image")
        self._image_generation_root = image_generation_models_root()
        self._image_generator_root = image_generator_models_root()
        self._models: Dict[str, SynthesisModelInfo] = {}
        self.reload()

    def _read_json(self, path: str) -> dict:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        return payload if isinstance(payload, dict) else {}

    def _register(self, model: SynthesisModelInfo) -> None:
        self._models[model.model_id] = model

    def _seed_defaults(self) -> None:
        self._register(
            SynthesisModelInfo(
                model_id="z_image_turbo",
                label="Z-Image-Turbo (Tongyi-MAI)",
                family="z-image",
                source="huggingface",
                installed=False,
                hf_repo_id="Tongyi-MAI/Z-Image-Turbo",
                default=True,
                defaults={
                    "width": 1024,
                    "height": 1024,
                    "num_inference_steps": 9,
                    "guidance_scale": 0.0,
                },
            )
        )
        self._register(
            SynthesisModelInfo(
                model_id="stable_diffusion_v1_5",
                label="Stable Diffusion v1.5 (RunwayML)",
                family="stable-diffusion",
                source="huggingface",
                installed=False,
                hf_repo_id="runwayml/stable-diffusion-v1-5",
                default=False,
                defaults={
                    "width": 768,
                    "height": 768,
                    "num_inference_steps": 30,
                    "guidance_scale": 7.0,
                },
            )
        )
        self._register(
            SynthesisModelInfo(
                model_id="stable_diffusion_webui",
                label="Stable Diffusion WebUI API",
                family="stable-diffusion-webui",
                source="remote",
                installed=True,
                default=False,
                defaults={
                    "width": 768,
                    "height": 768,
                    "num_inference_steps": 30,
                    "guidance_scale": 2.0,
                },
            )
        )
        self._register(
            SynthesisModelInfo(
                model_id="comfyui_txt2img",
                label="ComfyUI API",
                family="comfyui",
                source="remote",
                installed=True,
                default=False,
                defaults={
                    "width": 1024,
                    "height": 1024,
                    "num_inference_steps": 30,
                    "guidance_scale": 7.0,
                    "scheduler": "euler",
                },
            )
        )

    def _collect_from_manifest(self, directory: str, manifest: dict) -> Optional[SynthesisModelInfo]:
        model_id = str(manifest.get("id") or manifest.get("model_id") or "").strip()
        if not model_id:
            return None

        label = str(manifest.get("label") or model_id).strip()
        family = str(manifest.get("family") or "diffusion").strip().lower()
        source = str(manifest.get("source") or "local").strip().lower()
        hf_repo_id = manifest.get("hf_repo_id") or manifest.get("repo_id")
        path = manifest.get("path")
        if path:
            if not os.path.isabs(path):
                path = os.path.join(directory, path)
            path = os.path.normpath(path)
        elif source == "local":
            path = directory

        vae_path = manifest.get("vae_path") or manifest.get("vae")
        if vae_path:
            if not os.path.isabs(vae_path):
                vae_path = os.path.join(directory, vae_path)
            vae_path = os.path.normpath(vae_path)

        installed = _to_bool(
            manifest.get("installed"),
            default=(bool(path) and os.path.isdir(path)),
        )
        defaults = manifest.get("defaults")
        if not isinstance(defaults, dict):
            defaults = {}

        return SynthesisModelInfo(
            model_id=model_id,
            label=label,
            family=family,
            source=source,
            installed=installed,
            path=path,
            vae_path=(str(vae_path).strip() if vae_path else None),
            hf_repo_id=(str(hf_repo_id).strip() if hf_repo_id else None),
            default=_to_bool(manifest.get("default"), False),
            defaults=defaults,
        )

    def _collect_from_model_index(self, directory: str, model_index: dict) -> SynthesisModelInfo:
        folder_name = os.path.basename(directory)
        class_name = str(model_index.get("_class_name") or "")
        family = _infer_family(folder_name, class_name)
        defaults = {
            "width": 1024,
            "height": 1024,
            "num_inference_steps": 30,
            "guidance_scale": 7.0,
        }
        if family == "z-image":
            defaults.update({"num_inference_steps": 9, "guidance_scale": 0.0})

        return SynthesisModelInfo(
            model_id=folder_name,
            label=folder_name,
            family=family,
            source="local",
            installed=True,
            path=directory,
            defaults=defaults,
        )

    def _scan_local_models(self) -> List[SynthesisModelInfo]:
        items: List[SynthesisModelInfo] = []
        roots = [self._root, str(self._image_generation_root)]

        for root in roots:
            if not os.path.isdir(root):
                continue
            for entry in sorted(os.listdir(root)):
                directory = os.path.join(root, entry)
                if not os.path.isdir(directory):
                    continue

                manifest_path = os.path.join(directory, MODEL_MANIFEST_FILE)
                model_index_path = os.path.join(directory, MODEL_INDEX_FILE)

                try:
                    if os.path.isfile(manifest_path):
                        manifest = self._read_json(manifest_path)
                        model = self._collect_from_manifest(directory, manifest)
                        if model:
                            items.append(model)
                            continue

                    if os.path.isfile(model_index_path):
                        model_index = self._read_json(model_index_path)
                        items.append(self._collect_from_model_index(directory, model_index))
                except Exception as exc:
                    log_audit_entry(
                        "synthesis_model_registry_scan_error",
                        "[Synthesis] Failed to parse model metadata.",
                        AuditStatus.WARNING,
                        details={"directory": directory, "error": str(exc)},
                    )
        return items

    def _scan_image_generator_checkpoints(self) -> List[SynthesisModelInfo]:
        checkpoint_roots = [self._image_generator_root]
        legacy_diffuser_root = legacy_image_gen_diffuser_models_root()
        if legacy_diffuser_root.exists():
            checkpoint_roots.append(legacy_diffuser_root)
        legacy_root = legacy_image_generator_checkpoints_root()
        if legacy_root.exists():
            checkpoint_roots.append(legacy_root)
        items: List[SynthesisModelInfo] = []

        for checkpoints_root in checkpoint_roots:
            if not checkpoints_root.exists():
                continue
            for path in sorted(checkpoints_root.rglob("*"), key=lambda item: item.as_posix().lower()):
                if not path.is_file() or path.suffix.lower() not in CHECKPOINT_EXTENSIONS:
                    continue
                name_probe = path.stem.lower()
                family = "sdxl-checkpoint" if _looks_like_sdxl_checkpoint(name_probe) else "stable-diffusion-checkpoint"
                defaults = {
                    "width": 1024 if family == "sdxl-checkpoint" else 768,
                    "height": 1024 if family == "sdxl-checkpoint" else 768,
                    "num_inference_steps": 30,
                    "guidance_scale": 7.0,
                    "scheduler": "euler",
                    "sampler": "euler",
                }
                items.append(
                    SynthesisModelInfo(
                        model_id=_safe_model_id("image_gen", path.name),
                        label=path.stem,
                        family=family,
                        source="local",
                        installed=True,
                        path=str(path),
                        defaults=defaults,
                    )
                )
        return items

    def import_checkpoint(
        self,
        source_path: str,
        *,
        label: str = "",
        family: str = "auto",
        model_id: str = "",
        vae_path: str = "",
    ) -> SynthesisModelInfo:
        source = Path(str(source_path or "")).expanduser()
        if not source.is_absolute():
            source = Path.cwd() / source
        source = source.resolve()
        if not source.is_file():
            raise ValueError(f"Model file does not exist: {source}")

        suffix = source.suffix.lower()
        if suffix in UNSUPPORTED_IMAGE_MODEL_EXTENSIONS:
            raise ValueError(
                "GGUF image diffusion models are not supported by the current Diffusers provider. "
                "Use .safetensors or .ckpt checkpoints."
            )
        if suffix not in CHECKPOINT_EXTENSIONS:
            raise ValueError("Only .safetensors and .ckpt checkpoints are supported for local image generation.")

        inferred_family = self._infer_checkpoint_family(source.name, family)
        safe_id = _safe_slug(model_id or source.stem, "checkpoint")
        target_dir = self._image_generation_root / safe_id
        index = 2
        while target_dir.exists() and (target_dir / MODEL_MANIFEST_FILE).exists():
            safe_id = _safe_slug(f"{model_id or source.stem}_{index}", "checkpoint")
            target_dir = self._image_generation_root / safe_id
            index += 1
        target_dir.mkdir(parents=True, exist_ok=True)

        target_model_path = target_dir / f"checkpoint{suffix}"
        if source.resolve() != target_model_path.resolve():
            shutil.copy2(source, target_model_path)

        resolved_vae_path = self._resolve_optional_local_path(vae_path)
        manifest = {
            "id": safe_id,
            "label": str(label or source.stem).strip() or safe_id,
            "family": inferred_family,
            "source": "local",
            "installed": True,
            "path": target_model_path.name,
            "vae_path": str(resolved_vae_path) if resolved_vae_path else "",
            "defaults": {
                "width": 1024 if inferred_family == "sdxl-checkpoint" else 768,
                "height": 1024 if inferred_family == "sdxl-checkpoint" else 768,
                "num_inference_steps": 30,
                "guidance_scale": 7.0,
                "scheduler": "euler",
                "sampler": "euler",
            },
        }
        (target_dir / MODEL_MANIFEST_FILE).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.reload()
        model = self.get_model(safe_id)
        if model is None:
            raise ValueError(f"Imported model was not registered: {safe_id}")
        return model

    @staticmethod
    def _resolve_optional_local_path(value: str) -> Optional[Path]:
        raw = str(value or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        path = path.resolve()
        if not path.exists():
            raise ValueError(f"VAE path does not exist: {path}")
        return path

    @staticmethod
    def _infer_checkpoint_family(filename: str, requested_family: str = "auto") -> str:
        family = str(requested_family or "auto").strip().lower()
        aliases = {
            "sd": "stable-diffusion-checkpoint",
            "sd15": "stable-diffusion-checkpoint",
            "stable-diffusion": "stable-diffusion-checkpoint",
            "stable_diffusion": "stable-diffusion-checkpoint",
            "sdxl": "sdxl-checkpoint",
            "xl": "sdxl-checkpoint",
        }
        family = aliases.get(family, family)
        if family in {"stable-diffusion-checkpoint", "sdxl-checkpoint"}:
            return family
        name_probe = Path(filename).stem.lower()
        if _looks_like_sdxl_checkpoint(name_probe):
            return "sdxl-checkpoint"
        return "stable-diffusion-checkpoint"

    def _promote_local_over_remote(self) -> None:
        remote = self._models.get("z_image_turbo")
        if remote is None:
            return

        for model in self._models.values():
            if model.model_id == "z_image_turbo":
                continue
            if model.family == "z-image" and model.source == "local" and model.path:
                remote.source = "local"
                remote.path = model.path
                remote.installed = True
                remote.defaults = model.defaults or remote.defaults
                return

    def reload(self) -> None:
        self._models = {}
        self._seed_defaults()
        for model in self._scan_local_models():
            self._register(model)
        for model in self._scan_image_generator_checkpoints():
            self._register(model)

        self._promote_local_over_remote()

        # Ensure single default model
        default_set = False
        for model in self._models.values():
            if model.default and not default_set:
                default_set = True
            elif model.default and default_set:
                model.default = False

        if not default_set and self._models:
            first_key = sorted(self._models.keys())[0]
            self._models[first_key].default = True

        log_audit_entry(
            "synthesis_model_registry_loaded",
            "[Synthesis] Model registry refreshed.",
            AuditStatus.INFO,
            details={
                "root": self._root,
                "count": len(self._models),
                "models": [asdict(m) for m in self._models.values()],
            },
        )

    def get_default_model_id(self) -> Optional[str]:
        for model in self._models.values():
            if model.default:
                return model.model_id
        return next(iter(self._models.keys()), None)

    def list_models(self) -> List[SynthesisModelInfo]:
        return [self._models[key] for key in sorted(self._models.keys())]

    def get_model(self, model_id: str) -> Optional[SynthesisModelInfo]:
        return self._models.get(model_id)
