from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Dict, List, Optional

from constants.paths import DIFFUSER_MODELS_DIR
from modules.synthesis.types import SynthesisModelInfo
from services.logger_service import AuditStatus, log_audit_entry

MODEL_MANIFEST_FILE = "synthesis.model.json"
MODEL_INDEX_FILE = "model_index.json"


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


class SynthesisModelRegistry:
    def __init__(self) -> None:
        self._root = os.path.join(DIFFUSER_MODELS_DIR, "image")
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
        if not os.path.isdir(self._root):
            return []

        items: List[SynthesisModelInfo] = []
        for entry in sorted(os.listdir(self._root)):
            directory = os.path.join(self._root, entry)
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

