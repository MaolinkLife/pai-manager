from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

from constants.paths import BASE_DIR, PROJECT_DIR, RVC_MODELS_DIR
from services.logger_service import AuditStatus, log_audit_entry


BACKEND_ROOT = Path(BASE_DIR)
LOCAL_RVC_ROOT = Path(RVC_MODELS_DIR)
LOCAL_RVC_EMBEDDERS = LOCAL_RVC_ROOT / "embedder"
LOCAL_RVC_BASE = LOCAL_RVC_ROOT / "rvc_base"
LOCAL_RVC_VOICES = LOCAL_RVC_ROOT / "rvc_voices"
LEGACY_RVC_ROOT = Path(PROJECT_DIR) / "models" / "RVC"
LOCAL_VENDOR_ROOT = BACKEND_ROOT / "vendor" / "rvc_site_packages"

RVC_BASE_FILES = [
    "fcpe.pt",
    "rmvpe.onnx",
    "rmvpe.pt",
]
RVC_EMBEDDER_FILES = {
    "hubert": "hubert_base.pt",
    "contentvec": "contentvec_base.pt",
}
RVC_F0_METHODS = ["fcpe", "rmvpe", "crepe", "pm", "dio"]
RVC_EMBEDDER_MODELS = ["hubert", "contentvec"]


def ensure_rvc_paths() -> None:
    LOCAL_RVC_EMBEDDERS.mkdir(parents=True, exist_ok=True)
    LOCAL_RVC_BASE.mkdir(parents=True, exist_ok=True)
    LOCAL_RVC_VOICES.mkdir(parents=True, exist_ok=True)
    LOCAL_VENDOR_ROOT.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_rvc_root()


def _migrate_legacy_rvc_root() -> None:
    """
    Move legacy project-root models/RVC assets into backend/storage/models/rvc.
    Safe behavior:
    - Never overwrites existing files in new location.
    - Keeps any conflicting legacy files in place.
    """
    if not LEGACY_RVC_ROOT.exists() or not LEGACY_RVC_ROOT.is_dir():
        return
    if LEGACY_RVC_ROOT.resolve() == LOCAL_RVC_ROOT.resolve():
        return

    moved_any = False
    for source_path in LEGACY_RVC_ROOT.rglob("*"):
        if source_path.is_dir():
            continue
        relative = source_path.relative_to(LEGACY_RVC_ROOT)
        target_path = LOCAL_RVC_ROOT / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if target_path.exists():
            continue
        try:
            source_path.replace(target_path)
            moved_any = True
        except Exception:
            continue

    # Try to remove empty legacy directories (best effort).
    for directory in sorted(LEGACY_RVC_ROOT.rglob("*"), reverse=True):
        if directory.is_dir():
            try:
                directory.rmdir()
            except OSError:
                pass
    try:
        LEGACY_RVC_ROOT.rmdir()
    except OSError:
        pass
    try:
        legacy_models_root = LEGACY_RVC_ROOT.parent
        if legacy_models_root.exists():
            legacy_models_root.rmdir()
    except OSError:
        pass

    if moved_any:
        log_audit_entry(
            "rvc_models_migrated",
            "[RVC] Migrated legacy models/RVC into backend/storage/models/rvc.",
            AuditStatus.SUCCESS,
            details={
                "legacy_root": str(LEGACY_RVC_ROOT),
                "target_root": str(LOCAL_RVC_ROOT),
            },
        )


def ensure_rvc_vendor_pythonpath() -> None:
    candidate_path = str(LOCAL_VENDOR_ROOT)
    if LOCAL_VENDOR_ROOT.exists() and candidate_path not in sys.path:
        sys.path.append(candidate_path)


def ensure_rvc_bootstrap() -> None:
    ensure_rvc_paths()
    ensure_rvc_vendor_pythonpath()


def list_local_rvc_models() -> list[dict[str, str]]:
    ensure_rvc_bootstrap()
    files: list[dict[str, str]] = []
    seen: set[str] = set()

    candidates: list[Path] = []
    candidates.extend(sorted(LOCAL_RVC_VOICES.glob("*.pth")))
    candidates.extend(sorted(LOCAL_RVC_ROOT.glob("*.pth")))
    candidates.extend(sorted(LOCAL_RVC_ROOT.rglob("*.pth")))

    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        try:
            rel_path = path.relative_to(LOCAL_RVC_ROOT).as_posix()
        except ValueError:
            rel_path = path.name
        if rel_path in seen:
            continue
        seen.add(rel_path)
        files.append({"name": path.name, "path": rel_path})

    files.sort(key=lambda item: item["path"])
    return files


def resolve_rvc_model_path(model_file: str | None) -> Path | None:
    ensure_rvc_bootstrap()
    raw_value = str(model_file or "").strip()
    if not raw_value:
        return None

    candidate = Path(raw_value)
    if candidate.is_absolute() and candidate.exists() and candidate.is_file():
        return candidate

    local_candidate = (LOCAL_RVC_VOICES / raw_value).resolve()
    if local_candidate.exists() and local_candidate.is_file():
        return local_candidate

    root_candidate = (LOCAL_RVC_ROOT / raw_value).resolve()
    if root_candidate.exists() and root_candidate.is_file():
        return root_candidate

    target_name = Path(raw_value).name
    for path in LOCAL_RVC_ROOT.rglob("*.pth"):
        if path.name == target_name and path.exists() and path.is_file():
            return path.resolve()

    return None


def rvc_base_assets_ready() -> bool:
    ensure_rvc_bootstrap()
    return all((LOCAL_RVC_BASE / name).exists() for name in RVC_BASE_FILES)


def rvc_f0_assets_ready(f0_method: str | None) -> bool:
    ensure_rvc_bootstrap()
    method = str(f0_method or "").strip().lower()
    if method == "fcpe":
        return (LOCAL_RVC_BASE / "fcpe.pt").exists()
    if method == "rmvpe":
        return (LOCAL_RVC_BASE / "rmvpe.pt").exists()
    return True


def resolve_rvc_embedder_path(embedder_model: str | None) -> Path | None:
    ensure_rvc_bootstrap()
    model_name = str(embedder_model or "").strip().lower()
    file_name = RVC_EMBEDDER_FILES.get(model_name)
    if not file_name:
        return None

    candidate = (LOCAL_RVC_EMBEDDERS / file_name).resolve()
    if candidate.exists() and candidate.is_file():
        return candidate

    legacy_candidate = (LOCAL_RVC_ROOT / file_name).resolve()
    if legacy_candidate.exists() and legacy_candidate.is_file():
        log_audit_entry(
            "rvc_embedder_legacy_path_used",
            "[RVC] Using legacy embedder path. Move embedder files into models/RVC/embedder.",
            AuditStatus.WARNING,
            details={
                "embedder_model": model_name,
                "legacy_path": str(legacy_candidate),
                "expected_path": str(candidate),
            },
        )
        return legacy_candidate
    return None


def rvc_embedder_ready(embedder_model: str | None) -> bool:
    return resolve_rvc_embedder_path(embedder_model) is not None


def detect_rvc_dependency_status() -> dict[str, bool]:
    ensure_rvc_vendor_pythonpath()
    modules = {
        "fairseq": False,
        "local_attention": False,
        "torchcrepe": False,
        "pyworld": False,
        "parselmouth": False,
        "ffmpeg": False,
    }

    for module_name in list(modules.keys()):
        modules[module_name] = importlib.util.find_spec(module_name) is not None
    return modules


def available_rvc_f0_methods() -> list[str]:
    deps = detect_rvc_dependency_status()
    methods: list[str] = []
    if deps["local_attention"]:
        methods.extend(["fcpe", "rmvpe"])
    if deps["torchcrepe"]:
        methods.append("crepe")
    if deps["parselmouth"]:
        methods.append("pm")
    if deps["pyworld"]:
        methods.append("dio")
    return methods


def get_rvc_status(config: dict[str, Any] | None = None, *, last_error: str | None = None) -> dict[str, Any]:
    ensure_rvc_bootstrap()
    rvc_config = config or {}
    selected_model = resolve_rvc_model_path(rvc_config.get("model_file"))
    available_methods = available_rvc_f0_methods()
    dependency_status = detect_rvc_dependency_status()
    enabled = bool(rvc_config.get("enabled", False))
    selected_f0_method = str(rvc_config.get("f0_method") or "fcpe").strip().lower()
    selected_embedder = str(rvc_config.get("embedder_model") or "hubert").strip().lower()
    base_assets_ready = rvc_f0_assets_ready(selected_f0_method)
    embedder_ready = rvc_embedder_ready(selected_embedder)
    fallback_active = enabled and (
        selected_model is None
        or not base_assets_ready
        or not embedder_ready
        or not available_methods
        or bool(last_error)
    )

    return {
        "enabled": enabled,
        "model_selected": selected_model is not None,
        "model_file": selected_model.name if selected_model else str(rvc_config.get("model_file") or ""),
        "base_assets_ready": base_assets_ready,
        "embedder_ready": embedder_ready,
        "available_f0_methods": available_methods,
        "available_embedder_models": list(RVC_EMBEDDER_MODELS),
        "dependency_status": dependency_status,
        "local_models_count": len(list_local_rvc_models()),
        "last_error": last_error,
        "fallback_active": fallback_active,
        "preload_state": "disabled" if not enabled else "idle",
        "model_loaded": False,
        "loaded_model_file": "",
        "embedder_loaded": False,
        "f0_method_ready": False,
    }
