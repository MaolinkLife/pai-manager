from __future__ import annotations

import gc
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
from pydub import AudioSegment

from constants.paths import PROJECT_DIR, RVC_MODELS_DIR, TTS_MODELS_DIR
from modules.tts.ffmpeg_tools import find_binary
from modules.tts.paths import create_temp_audio_file, voices_root
from modules.tts.providers.base import TTSProvider, TTSProviderError
from modules.tts.types import TTSRequest, TTSResult
from modules.tts.voice_import import ensure_xtts_reference_file
from services.rvc_bootstrap_service import (
    ensure_rvc_bootstrap,
    get_rvc_status,
    resolve_rvc_embedder_path,
    resolve_rvc_model_path,
)
from services.logger_service import AuditStatus, log_audit_entry

try:
    from TTS.api import TTS as CoquiTTS

    COQUI_AVAILABLE = True
except ImportError:
    CoquiTTS = None
    COQUI_AVAILABLE = False

try:
    import torch
except ImportError:
    torch = None

try:
    import deepspeed  # noqa: F401

    DEEPSPEED_AVAILABLE = True
except ImportError:
    DEEPSPEED_AVAILABLE = False

logging.getLogger("TTS").setLevel(logging.WARNING)
logging.getLogger("TTS.api").setLevel(logging.WARNING)
logging.getLogger("TTS.utils.synthesizer").setLevel(logging.WARNING)

XTTS_MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"
XTTS_REPO_ID = "coqui/XTTS-v2"
_XTTS_AUDIO_PATCHED = False


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(value, (int, float)):
        return bool(value)
    return False


class CoquiTTSProvider(TTSProvider):
    name = "coqui"

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        self._config = dict(config or {})
        self._engine = None
        self._engine_lock = threading.Lock()
        self._last_init_error: Optional[str] = None
        self._preload_thread: Optional[threading.Thread] = None
        self._model_name = self._config.get("model_name", XTTS_MODEL_NAME)
        self._model_revision = str(self._config.get("model_revision") or "main").strip() or "main"
        self._xtts_repo_id = str(self._config.get("hf_repo_id") or XTTS_REPO_ID).strip() or XTTS_REPO_ID
        self._speaker = self._config.get("speaker") or None
        self._speaker_wav = self._config.get("speaker_wav") or None
        self._language = self._config.get("language", "ru")
        self._device = (self._config.get("device") or "cpu").lower()
        self._preload_model = _as_bool(self._config.get("preload_model", False))
        self._keep_model_loaded = _as_bool(self._config.get("keep_model_loaded", True))
        self._use_deepspeed_requested = _as_bool(
            self._config.get("use_deepspeed", self._config.get("use_deep_speed", False))
        )
        self._low_ram_mode = _as_bool(self._config.get("low_ram_mode", False))
        self._speed = self._coerce_float(self._config.get("speed"), 1.0)
        self._enable_sentence_splitting = _as_bool(self._config.get("enable_sentence_splitting", True))
        self._temperature = self._coerce_float(self._config.get("temperature"), 0.3)
        self._length_penalty = self._coerce_float(self._config.get("length_penalty"), 1.0)
        self._repetition_penalty = self._coerce_float(self._config.get("repetition_penalty"), 2.0)
        self._top_k = self._coerce_int(self._config.get("top_k"), 50)
        self._top_p = self._coerce_float(self._config.get("top_p"), 0.85)
        self._gpt_cond_len = self._coerce_int(self._config.get("gpt_cond_len"), 20)
        self._gpt_cond_chunk_len = self._coerce_int(self._config.get("gpt_cond_chunk_len"), 6)
        self._max_ref_len = self._coerce_int(self._config.get("max_ref_len"), 30)
        self._sound_norm_refs = _as_bool(self._config.get("sound_norm_refs", False))
        self._rvc_config = dict(self._config.get("rvc") or {})
        self._rvc_last_error: Optional[str] = None
        self._rvc_lock = threading.Lock()
        self._preload_state = "idle" if self._preload_model else "disabled"
        self._rvc_preload_state = (
            "idle"
            if _as_bool(self._rvc_config.get("enabled", False))
            else "disabled"
        )
        self._rvc_model_loaded = False
        self._rvc_loaded_model_file = ""
        self._rvc_embedder_loaded = False
        self._rvc_f0_method_ready = False
        self._local_model_assets = self._resolve_local_model_assets()
        ensure_rvc_bootstrap()

        log_audit_entry(
            "coqui_provider_init",
            "[Coqui] Provider initialized.",
            AuditStatus.INFO,
            details={
                "installed": COQUI_AVAILABLE,
                "model_name": self._model_name,
                "model_revision": self._model_revision,
                "hf_repo_id": self._xtts_repo_id,
                "language": self._language,
                "device": self._device,
                "effective_device": self._effective_device(),
                "preload_model": self._preload_model,
                "keep_model_loaded": self._keep_model_loaded,
                "use_deepspeed_requested": self._use_deepspeed_requested,
                "deepspeed_available": DEEPSPEED_AVAILABLE,
                "use_deepspeed": self._can_use_deepspeed(),
                "low_ram_mode": self._low_ram_mode,
                "temperature": self._temperature,
                "length_penalty": self._length_penalty,
                "repetition_penalty": self._repetition_penalty,
                "top_k": self._top_k,
                "top_p": self._top_p,
                "gpt_cond_len": self._gpt_cond_len,
                "gpt_cond_chunk_len": self._gpt_cond_chunk_len,
                "max_ref_len": self._max_ref_len,
                "sound_norm_refs": self._sound_norm_refs,
                "rvc": get_rvc_status(self._rvc_config),
                "local_model_enabled": bool(self._local_model_assets),
                "local_model_path": (
                    self._local_model_assets.get("model_path")
                    if self._local_model_assets
                    else None
                ),
                "runtime": self._cuda_diagnostics(),
            },
        )

        if self._low_ram_mode and not self._can_use_cuda():
            log_audit_entry(
                "coqui_low_ram_unavailable",
                "[Coqui] Low RAM mode requires CUDA and has been disabled.",
                AuditStatus.WARNING,
                details=self._cuda_diagnostics(),
            )
            self._low_ram_mode = False

        if self._is_cuda_requested() and not self._can_use_cuda():
            log_audit_entry(
                "coqui_cuda_unavailable",
                "[Coqui] CUDA was requested but is not available. Falling back to CPU.",
                AuditStatus.WARNING,
                details=self._cuda_diagnostics(),
            )

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _is_cuda_requested(self) -> bool:
        return self._device == "cuda"

    def _can_use_cuda(self) -> bool:
        return bool(self._is_cuda_requested() and torch is not None and torch.cuda.is_available())

    def _effective_device(self) -> str:
        if self._can_use_cuda():
            return "cuda"
        return "cpu"

    def _low_ram_active(self) -> bool:
        return bool(self._low_ram_mode and self._can_use_cuda())

    def _cuda_diagnostics(self) -> Dict[str, Any]:
        if torch is None:
            return {
                "torch_installed": False,
                "torch_version": None,
                "cuda_available": False,
                "cuda_version": None,
                "device_count": 0,
            }

        cuda_available = bool(torch.cuda.is_available())
        return {
            "torch_installed": True,
            "torch_version": getattr(torch, "__version__", None),
            "cuda_available": cuda_available,
            "cuda_version": getattr(torch.version, "cuda", None),
            "device_count": torch.cuda.device_count() if cuda_available else 0,
        }

    def _can_use_deepspeed(self) -> bool:
        return bool(
            self._use_deepspeed_requested
            and DEEPSPEED_AVAILABLE
            and self._can_use_cuda()
            and self._is_xtts_model()
        )

    def _release_cuda_cache(self) -> None:
        gc.collect()
        if torch is None or not torch.cuda.is_available():
            return
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        try:
            torch.cuda.ipc_collect()
        except Exception:
            pass

    def _move_engine_to_device(self, engine: Any, target_device: str) -> None:
        try:
            if hasattr(engine, "to"):
                engine.to(target_device)
        except Exception:
            pass

        synthesizer = getattr(engine, "synthesizer", None)
        if synthesizer is not None:
            try:
                tts_model = getattr(synthesizer, "tts_model", None)
                if tts_model is not None and hasattr(tts_model, "to"):
                    tts_model.to(target_device)
            except Exception:
                pass

    def _is_xtts_model(self) -> bool:
        return "xtts" in str(self._model_name or "").lower()

    @staticmethod
    def _sanitize_revision_name(revision: str) -> str:
        safe_revision = re.sub(r"[^A-Za-z0-9._-]+", "_", revision.strip())
        return safe_revision or "main"

    def _project_root(self) -> Path:
        return Path(PROJECT_DIR)

    def _xtts_models_root(self) -> Path:
        return Path(TTS_MODELS_DIR) / "xtts"

    def _resolved_hf_revision(self) -> str:
        normalized = self._model_revision.strip().lower()
        if normalized.startswith("xttsv2_"):
            return f"v{normalized[len('xttsv2_') :]}"
        if normalized == "main":
            return "main"
        if re.fullmatch(r"\d+\.\d+\.\d+", normalized):
            return f"v{normalized}"
        return self._model_revision.strip() or "main"

    def _canonical_xtts_revision_dir_name(self) -> str:
        hf_revision = self._resolved_hf_revision()
        if hf_revision == "main":
            return "main"
        if re.fullmatch(r"v\d+\.\d+\.\d+", hf_revision):
            return f"xttsv2_{hf_revision[1:]}"
        return self._sanitize_revision_name(self._model_revision)

    def _xtts_revision_dirs(self) -> list[Path]:
        root = self._xtts_models_root()
        if self._model_revision == "main":
            return [root]

        candidates = [root / self._canonical_xtts_revision_dir_name()]

        safe_revision = self._sanitize_revision_name(self._model_revision)
        if safe_revision != candidates[0].name:
            candidates.append(root / safe_revision)

        hf_revision = self._resolved_hf_revision()
        safe_hf_revision = self._sanitize_revision_name(hf_revision)
        if safe_hf_revision not in {path.name for path in candidates}:
            candidates.append(root / safe_hf_revision)

        return candidates

    def _available_xtts_model_dirs(self) -> list[Path]:
        root = self._xtts_models_root()
        if not root.exists() or not root.is_dir():
            return []

        candidates: list[Path] = []
        for child in root.iterdir():
            if child.is_dir():
                candidates.append(child)

        def sort_key(path: Path) -> tuple[int, str]:
            name = path.name.lower()
            match = re.search(r"(\d+)\.(\d+)\.(\d+)", name)
            if match:
                return (
                    int(match.group(1)),
                    int(match.group(2)),
                    int(match.group(3)),
                )
            return (-1, -1, -1)

        return sorted(candidates, key=lambda path: (sort_key(path), path.name.lower()), reverse=True)

    def _voices_root(self) -> Path:
        return voices_root()

    def _tts_home_root(self) -> Path:
        return Path(TTS_MODELS_DIR) / ".tts_home"

    def _configure_local_ffmpeg(self) -> None:
        ffmpeg = find_binary("ffmpeg")
        ffprobe = find_binary("ffprobe")
        if ffmpeg is not None:
            AudioSegment.converter = str(ffmpeg)
        if ffprobe is not None:
            AudioSegment.ffprobe = str(ffprobe)

    def _patch_xtts_audio_loader(self) -> None:
        global _XTTS_AUDIO_PATCHED
        if _XTTS_AUDIO_PATCHED or not self._is_xtts_model() or torch is None:
            return

        self._configure_local_ffmpeg()

        try:
            from TTS.tts.models import xtts as xtts_module
        except Exception:
            return

        def _load_audio_with_pydub(audiopath, sampling_rate):
            segment = AudioSegment.from_file(audiopath)
            if segment.channels != 1:
                segment = segment.set_channels(1)
            if segment.frame_rate != sampling_rate:
                segment = segment.set_frame_rate(sampling_rate)

            samples = np.array(segment.get_array_of_samples(), dtype=np.float32)
            max_value = float(1 << (8 * segment.sample_width - 1))
            if max_value > 0:
                samples /= max_value

            audio_tensor = torch.from_numpy(samples).unsqueeze(0)
            audio_tensor = audio_tensor.clamp_(-1.0, 1.0)
            return audio_tensor

        xtts_module.load_audio = _load_audio_with_pydub
        _XTTS_AUDIO_PATCHED = True
        log_audit_entry(
            "coqui_xtts_audio_loader_patched",
            "[Coqui] XTTS audio loader patched to use local FFmpeg/PyDub.",
            AuditStatus.INFO,
        )

    def _ensure_tts_home_env(self) -> None:
        tts_home = self._tts_home_root()
        tts_home.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("TTS_HOME", str(tts_home))

    def _resolve_model_name_path(self) -> Optional[Path]:
        raw_value = str(self._model_name or "").strip()
        if not raw_value:
            return None

        raw_path = Path(raw_value).expanduser()
        candidates = [raw_path]
        if not raw_path.is_absolute():
            candidates.append(self._project_root() / raw_path)

        for candidate in candidates:
            if candidate.exists():
                return candidate

        normalized = raw_value.replace("\\", "/").lower()
        if not raw_path.is_absolute() and normalized.startswith(
            ("models/", "./models/", ".\\models\\", "storage/models/", "./storage/models/")
        ):
            # Backward compatibility: route model-relative paths to storage/models.
            cleaned = normalized.lstrip("./")
            if cleaned.startswith("storage/models/"):
                relative = cleaned[len("storage/models/") :]
                return Path(TTS_MODELS_DIR).parent / relative
            if cleaned.startswith("models/"):
                relative = cleaned[len("models/") :]
                return Path(TTS_MODELS_DIR).parent / relative
            return Path(TTS_MODELS_DIR).parent / str(raw_path).replace("\\", "/")

        return None

    @staticmethod
    def _find_existing_file(base_dir: Path, candidates: list[str]) -> Optional[Path]:
        for candidate in candidates:
            direct = base_dir / candidate
            if direct.exists() and direct.is_file():
                return direct

        for candidate in candidates:
            matches = sorted(base_dir.glob(candidate))
            for match in matches:
                if match.is_file():
                    return match
        return None

    def _build_asset_map(self, model_path: Path, config_path: Path, base_dir: Path) -> Dict[str, str]:
        assets: Dict[str, str] = {
            "model_path": str(model_path),
            "config_path": str(config_path),
        }

        speakers_file = self._find_existing_file(
            base_dir,
            ["speakers_xtts.pth", "speakers.pth", "speakers.json"],
        )
        if speakers_file is not None:
            assets["speakers_file_path"] = str(speakers_file)

        language_ids_file = self._find_existing_file(
            base_dir,
            ["language_ids.json", "languages.json"],
        )
        if language_ids_file is not None:
            assets["language_ids_file_path"] = str(language_ids_file)

        return assets

    def _collect_model_assets(self, base_dir: Path) -> Dict[str, str]:
        if not base_dir.exists() or not base_dir.is_dir():
            return {}

        model_path = self._find_existing_file(
            base_dir,
            ["model.pth", "best_model.pth", "checkpoint.pth", "*.pth"],
        )
        config_path = self._find_existing_file(base_dir, ["config.json"])
        if model_path is None or config_path is None:
            return {}

        return self._build_asset_map(model_path, config_path, base_dir)

    def _resolve_local_model_assets(self) -> Dict[str, str]:
        explicit_model_path = self._config.get("model_path")
        explicit_config_path = self._config.get("config_path")

        if explicit_model_path and explicit_config_path:
            model_path = Path(str(explicit_model_path)).expanduser()
            config_path = Path(str(explicit_config_path)).expanduser()
            if model_path.exists() and config_path.exists():
                return self._build_asset_map(model_path, config_path, config_path.parent)

        model_name_path = self._resolve_model_name_path()
        if model_name_path is not None:
            if model_name_path.is_dir():
                direct_assets = self._collect_model_assets(model_name_path)
                if direct_assets:
                    return direct_assets

                for child in sorted(
                    (path for path in model_name_path.iterdir() if path.is_dir()),
                    key=lambda path: path.name.lower(),
                    reverse=True,
                ):
                    child_assets = self._collect_model_assets(child)
                    if child_assets:
                        return child_assets

        if not self._is_xtts_model():
            return {}

        for revision_dir in self._xtts_revision_dirs():
            revision_assets = self._collect_model_assets(revision_dir)
            if revision_assets:
                return revision_assets

        if self._model_revision == "main":
            root_assets = self._collect_model_assets(self._xtts_models_root())
            if root_assets:
                return root_assets

            for model_dir in self._available_xtts_model_dirs():
                model_assets = self._collect_model_assets(model_dir)
                if model_assets:
                    return model_assets

        return {}

    def _should_download_xtts_revision(self) -> bool:
        if not self._is_xtts_model():
            return False
        return bool(re.fullmatch(r"(xttsv2_)?\d+\.\d+\.\d+|xttsv2_\d+\.\d+\.\d+", self._model_revision.strip().lower()))

    def _download_xtts_revision_assets(self) -> Dict[str, str]:
        target_dir = self._xtts_revision_dirs()[0]
        target_dir.mkdir(parents=True, exist_ok=True)

        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise TTSProviderError(
                "XTTS revision downloads require the 'huggingface_hub' package in the backend environment"
            ) from exc

        download_kwargs: Dict[str, Any] = {
            "repo_id": self._xtts_repo_id,
            "revision": self._resolved_hf_revision(),
            "local_dir": str(target_dir),
        }

        try:
            snapshot_download(local_dir_use_symlinks=False, **download_kwargs)
        except TypeError:
            snapshot_download(**download_kwargs)

        assets = self._collect_model_assets(target_dir)
        if not assets:
            raise TTSProviderError(
                f"XTTS revision '{self._model_revision}' was downloaded but model files were not found in {target_dir}"
            )

        try:
            from TTS.utils.manage import ModelManager

            ModelManager(progress_bar=False)._update_paths(target_dir, Path(assets["config_path"]))
        except Exception:
            pass

        return self._collect_model_assets(target_dir) or assets

    def _collect_wavs_from_dir(self, voice_dir: Path) -> list[str]:
        wavs = sorted(str(path) for path in voice_dir.glob("*.wav") if path.is_file())
        return wavs

    def _resolve_voice_reference(self, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, (list, tuple)):
            resolved_items = [self._resolve_voice_reference(item) for item in value]
            flattened: list[str] = []
            for item in resolved_items:
                if isinstance(item, list):
                    flattened.extend(item)
                elif isinstance(item, str):
                    flattened.append(item)
            return self._prepare_xtts_reference(flattened or None)

        raw_value = str(value).strip()
        if not raw_value:
            return None

        candidates: list[Path] = []
        raw_path = Path(raw_value).expanduser()
        candidates.append(raw_path)
        if not raw_path.is_absolute():
            candidates.append(self._project_root() / raw_path)
            candidates.append(self._voices_root() / raw_path)

        for candidate in candidates:
            if candidate.is_file():
                return self._prepare_xtts_reference(str(candidate))
            if candidate.is_dir():
                wavs = self._collect_wavs_from_dir(candidate)
                if wavs:
                    return self._prepare_xtts_reference(wavs)

        voices_root = self._voices_root()
        if not voices_root.exists():
            return None

        if raw_path.suffix:
            recursive_matches = sorted(path for path in voices_root.rglob(raw_path.name) if path.is_file())
            if recursive_matches:
                return self._prepare_xtts_reference(str(recursive_matches[0]))
        else:
            matching_dir = voices_root / raw_value
            if matching_dir.is_dir():
                wavs = self._collect_wavs_from_dir(matching_dir)
                if wavs:
                    return self._prepare_xtts_reference(wavs)

            recursive_dir_matches = sorted(
                path for path in voices_root.rglob(raw_value) if path.is_dir()
            )
            for match in recursive_dir_matches:
                wavs = self._collect_wavs_from_dir(match)
                if wavs:
                    return self._prepare_xtts_reference(wavs)

            wav_matches = sorted(path for path in voices_root.rglob(f"{raw_value}.wav") if path.is_file())
            if wav_matches:
                return self._prepare_xtts_reference(str(wav_matches[0]))

        return None

    def _prepare_xtts_reference(self, value: Any) -> Any:
        if not self._is_xtts_model() or value is None:
            return value

        if isinstance(value, list):
            prepared_items: list[str] = []
            for item in value:
                prepared_item = self._prepare_xtts_reference(item)
                if isinstance(prepared_item, str):
                    prepared_items.append(prepared_item)
            return prepared_items or None

        if not isinstance(value, str):
            return value

        candidate = Path(value)
        if not candidate.exists() or not candidate.is_file():
            return value

        try:
            prepared = ensure_xtts_reference_file(candidate)
            prepared_path = str(prepared.get("path") or value).strip()
            if prepared.get("created") or prepared.get("reused"):
                log_audit_entry(
                    "coqui_xtts_reference_prepared",
                    "[Coqui] XTTS reference sample prepared for voice cloning.",
                    AuditStatus.INFO,
                    details={
                        "source_path": str(candidate),
                        "prepared_path": prepared_path,
                        "created": bool(prepared.get("created")),
                        "reused": bool(prepared.get("reused")),
                    },
                )
            return prepared_path or value
        except Exception as exc:
            log_audit_entry(
                "coqui_xtts_reference_prepare_failed",
                "[Coqui] Failed to prepare XTTS reference sample. Falling back to original file.",
                AuditStatus.WARNING,
                details={"path": str(candidate), "error": str(exc)},
            )
            return value

    def _apply_engine_voice_dir(self, engine: Any) -> None:
        if self._is_xtts_model():
            return

        voices_root = self._voices_root()
        if not voices_root.exists():
            return

        try:
            engine.voice_dir = voices_root
        except Exception:
            pass

        synthesizer = getattr(engine, "synthesizer", None)
        if synthesizer is not None:
            try:
                synthesizer.voice_dir = voices_root
            except Exception:
                pass

    def _apply_engine_asset_overrides(self, engine: Any, resolved_assets: Dict[str, str]) -> None:
        synthesizer = getattr(engine, "synthesizer", None)
        if synthesizer is None:
            return

        speakers_file_path = resolved_assets.get("speakers_file_path")
        if speakers_file_path:
            try:
                synthesizer.tts_speakers_file = speakers_file_path
            except Exception:
                pass

        language_ids_file_path = resolved_assets.get("language_ids_file_path")
        if language_ids_file_path:
            try:
                synthesizer.tts_languages_file = language_ids_file_path
            except Exception:
                pass

    def _build_engine(self):
        if not COQUI_AVAILABLE or CoquiTTS is None:
            raise TTSProviderError("Coqui TTS is not installed")

        self._configure_local_ffmpeg()
        self._patch_xtts_audio_loader()
        self._ensure_tts_home_env()

        resolved_assets = self._local_model_assets
        if not resolved_assets and self._should_download_xtts_revision():
            resolved_assets = self._download_xtts_revision_assets()
            self._local_model_assets = resolved_assets

        kwargs: Dict[str, Any]
        if resolved_assets:
            model_path = resolved_assets["model_path"]
            if self._is_xtts_model():
                model_path = str(Path(resolved_assets["config_path"]).parent)
            kwargs = {
                "model_path": model_path,
                "config_path": resolved_assets["config_path"],
                "progress_bar": False,
            }
        else:
            fallback_model_name = self._model_name
            if self._resolve_model_name_path() is not None and self._is_xtts_model():
                fallback_model_name = XTTS_MODEL_NAME
            kwargs = {
                "model_name": fallback_model_name,
                "progress_bar": False,
            }

        # Some TTS builds ignore unsupported kwargs, so we only pass deepspeed
        # when explicitly requested.
        if self._can_use_deepspeed():
            kwargs["deepspeed"] = True

        engine = CoquiTTS(**kwargs)
        target_device = self._effective_device()
        self._move_engine_to_device(engine, target_device)
        self._apply_engine_voice_dir(engine)
        if resolved_assets:
            self._apply_engine_asset_overrides(engine, resolved_assets)
        if self._low_ram_active():
            self._move_engine_to_device(engine, "cpu")
            self._release_cuda_cache()
        return engine

    def _ensure_engine(self):
        if self._engine is not None:
            return self._engine

        with self._engine_lock:
            if self._engine is not None:
                return self._engine

            try:
                self._engine = self._build_engine()
                self._last_init_error = None
                if self._preload_state != "error":
                    self._preload_state = "loaded"
                log_audit_entry(
                    "coqui_model_loaded",
                    "[Coqui] Model loaded successfully.",
                    AuditStatus.SUCCESS,
                    details={
                        "model_name": self._model_name,
                        "model_revision": self._model_revision,
                        "device": self._effective_device(),
                        "deepspeed": self._can_use_deepspeed(),
                        "local_model_path": (
                            self._local_model_assets.get("model_path")
                            if self._local_model_assets
                            else None
                        ),
                    },
                )
            except Exception as exc:
                self._last_init_error = str(exc)
                self._preload_state = "error"
                raise TTSProviderError(
                    f"Coqui model '{self._model_name}' failed to load: {exc}"
                ) from exc

        return self._engine

    def _preload_worker(self) -> None:
        try:
            self._run_preload()
            log_audit_entry(
                "coqui_preload_complete",
                "[Coqui] Background preload finished.",
                AuditStatus.SUCCESS,
                details={"device": self._effective_device()},
            )
        except Exception as exc:
            self._last_init_error = str(exc)
            self._preload_state = "error"
            log_audit_entry(
                "coqui_preload_failed",
                "[Coqui] Background preload failed.",
                AuditStatus.WARNING,
                details={"error": str(exc)},
            )
        finally:
            with self._engine_lock:
                self._preload_thread = None

    def _reset_rvc_runtime_state(self) -> None:
        self._rvc_model_loaded = False
        self._rvc_loaded_model_file = ""
        self._rvc_embedder_loaded = False
        self._rvc_f0_method_ready = False
        self._rvc_preload_state = (
            "idle"
            if _as_bool(self._rvc_config.get("enabled", False))
            else "disabled"
        )

    def _effective_rvc_f0_method(self) -> str:
        return str(self._rvc_config.get("f0_method") or "fcpe").strip().lower()

    def _effective_rvc_embedder(self) -> str:
        return str(self._rvc_config.get("embedder_model") or "hubert").strip().lower()

    def _preload_rvc_if_enabled(self) -> None:
        if not _as_bool(self._rvc_config.get("enabled", False)):
            self._rvc_last_error = None
            self._reset_rvc_runtime_state()
            return

        with self._rvc_lock:
            if (
                self._rvc_model_loaded
                and self._rvc_embedder_loaded
                and self._rvc_f0_method_ready
            ):
                self._rvc_preload_state = "loaded"
                return

            self._rvc_preload_state = "preloading"
            model_path = resolve_rvc_model_path(self._rvc_config.get("model_file"))
            if model_path is None:
                self._rvc_preload_state = "error"
                self._rvc_last_error = "RVC model file is not selected or missing."
                raise RuntimeError(self._rvc_last_error)

            embedder_model = self._effective_rvc_embedder()
            if resolve_rvc_embedder_path(embedder_model) is None:
                self._rvc_preload_state = "error"
                self._rvc_last_error = (
                    f"RVC embedder '{embedder_model}' is missing in {Path(RVC_MODELS_DIR) / 'embedder'}."
                )
                raise RuntimeError(self._rvc_last_error)

            rvc_status = get_rvc_status(self._rvc_config)
            available_methods = set(rvc_status.get("available_f0_methods") or [])
            f0_method = self._effective_rvc_f0_method()
            if f0_method not in available_methods:
                self._rvc_preload_state = "error"
                self._rvc_last_error = (
                    f"Selected RVC F0 method '{f0_method}' is not available."
                )
                raise RuntimeError(self._rvc_last_error)

            if not rvc_status.get("base_assets_ready"):
                self._rvc_preload_state = "error"
                self._rvc_last_error = (
                    f"Required RVC assets for '{f0_method}' are missing in {Path(RVC_MODELS_DIR) / 'rvc_base'}."
                )
                raise RuntimeError(self._rvc_last_error)

            try:
                from modules.tts.rvc.infer.infer import warmup_rvc_runtime

                runtime = warmup_rvc_runtime(
                    model_path=str(model_path),
                    embedder_model=embedder_model,
                    f0_method=f0_method,
                    debug_rvc=False,
                )
            except Exception as exc:
                self._rvc_preload_state = "error"
                self._rvc_last_error = str(exc)
                raise

            self._rvc_last_error = None
            self._rvc_model_loaded = bool(runtime.get("model_loaded"))
            self._rvc_loaded_model_file = str(
                runtime.get("loaded_model_file") or model_path.name
            )
            self._rvc_embedder_loaded = bool(runtime.get("embedder_loaded"))
            self._rvc_f0_method_ready = bool(runtime.get("f0_method_ready"))
            self._rvc_preload_state = "loaded"

    def _run_preload(self) -> None:
        self._preload_state = "preloading"
        self._ensure_engine()
        self._preload_rvc_if_enabled()
        self._preload_state = "loaded"

    def preload(self, *, blocking: bool = False) -> None:
        if not self._preload_model:
            return
        if blocking:
            self._run_preload()
            return
        self._start_preload()

    def _start_preload(self) -> None:
        with self._engine_lock:
            if (
                self._engine is not None
                and (
                    not _as_bool(self._rvc_config.get("enabled", False))
                    or self._rvc_preload_state == "loaded"
                )
            ):
                return
            if self._preload_thread is not None and self._preload_thread.is_alive():
                return
            self._preload_state = "preloading"
            self._preload_thread = threading.Thread(
                target=self._preload_worker,
                name="coqui-preload",
                daemon=True,
            )
            self._preload_thread.start()
        log_audit_entry(
            "coqui_preload_started",
            "[Coqui] Background preload started.",
            AuditStatus.INFO,
            details={"device": self._effective_device()},
        )

    def is_available(self) -> bool:
        return COQUI_AVAILABLE

    def describe_status(self) -> Dict[str, Any]:
        with self._engine_lock:
            preload_thread_alive = bool(
                self._preload_thread is not None and self._preload_thread.is_alive()
            )
            engine_loaded = self._engine is not None

        preload_state = self._preload_state
        if preload_thread_alive:
            preload_state = "preloading"
        elif engine_loaded and preload_state not in {"error", "preloading"}:
            preload_state = "loaded"

        rvc_status = get_rvc_status(self._rvc_config, last_error=self._rvc_last_error)
        rvc_status.update(
            {
                "preload_state": self._rvc_preload_state,
                "model_loaded": self._rvc_model_loaded,
                "loaded_model_file": self._rvc_loaded_model_file,
                "embedder_loaded": self._rvc_embedder_loaded,
                "f0_method_ready": self._rvc_f0_method_ready,
            }
        )

        return {
            "preload_enabled": self._preload_model,
            "preload_state": preload_state,
            "engine_loaded": engine_loaded,
            "keep_model_loaded": self._keep_model_loaded,
            "device_requested": self._device,
            "effective_device": self._effective_device(),
            "last_init_error": self._last_init_error,
            "rvc": rvc_status,
        }

    def _apply_rvc_if_enabled(self, wav_path: str) -> tuple[str, bool]:
        if not _as_bool(self._rvc_config.get("enabled", False)):
            self._rvc_last_error = None
            self._reset_rvc_runtime_state()
            return wav_path, False

        tmp_fd, rvc_output_path = create_temp_audio_file(prefix="coqui_rvc_", suffix=".wav")
        os.close(tmp_fd)

        model_path: Optional[Path] = None
        try:
            from modules.tts.rvc.infer.infer import infer_pipeline

            self._preload_rvc_if_enabled()
            model_path = resolve_rvc_model_path(self._rvc_config.get("model_file"))
            if model_path is None:
                raise RuntimeError("RVC model file is not selected or missing.")
            f0_method = self._effective_rvc_f0_method()

            infer_pipeline(
                self._coerce_int(self._rvc_config.get("pitch"), 0),
                self._coerce_int(self._rvc_config.get("filter_radius"), 3),
                0.0,
                self._coerce_float(self._rvc_config.get("rms_mix_rate"), 1.0),
                self._coerce_float(self._rvc_config.get("protect"), 0.5),
                128,
                f0_method,
                wav_path,
                rvc_output_path,
                str(model_path),
                "",
                _as_bool(self._rvc_config.get("split_audio", True)),
                _as_bool(self._rvc_config.get("autotune", False)),
                str(self._rvc_config.get("embedder_model") or "hubert").strip().lower(),
                0,
                False,
            )

            if not os.path.exists(rvc_output_path) or os.path.getsize(rvc_output_path) == 0:
                raise RuntimeError("RVC did not create an output audio file.")

            self._rvc_last_error = None
            return rvc_output_path, True
        except Exception as exc:
            self._rvc_last_error = str(exc)
            log_audit_entry(
                "coqui_rvc_fallback",
                "[Coqui] RVC conversion failed. Falling back to XTTS output.",
                AuditStatus.WARNING,
                details={
                    "error": str(exc),
                    "model_file": model_path.name if model_path else "",
                },
            )
            if os.path.exists(rvc_output_path):
                try:
                    os.remove(rvc_output_path)
                except OSError:
                    pass
            return wav_path, False

    def synthesize(self, request: TTSRequest, output_path: str) -> TTSResult:
        if not request.text.strip():
            raise TTSProviderError("Coqui cannot synthesize empty text")

        start = time.time()
        engine = None
        wav_fd, wav_path = create_temp_audio_file(prefix="coqui_", suffix=".wav")
        os.close(wav_fd)
        source_wav_path = wav_path
        cleanup_paths = {wav_path}

        try:
            engine = self._ensure_engine()
            if self._low_ram_active():
                self._move_engine_to_device(engine, "cuda")
            kwargs: Dict[str, Any] = {
                "text": request.text,
                "file_path": wav_path,
            }
            kwargs["split_sentences"] = self._enable_sentence_splitting

            language = request.language if request.language and request.language != "auto" else self._language
            if language:
                kwargs["language"] = language

            speaker_hint = request.voice or self._speaker
            resolved_speaker_wav = self._resolve_voice_reference(self._speaker_wav)
            if resolved_speaker_wav is None:
                resolved_speaker_wav = self._resolve_voice_reference(speaker_hint)

            if resolved_speaker_wav:
                kwargs["speaker_wav"] = resolved_speaker_wav
                if speaker_hint and not str(speaker_hint).lower().endswith(".pth"):
                    kwargs["speaker"] = str(speaker_hint)
            elif speaker_hint:
                kwargs["speaker"] = speaker_hint

            if self._is_xtts_model():
                kwargs["temperature"] = self._temperature
                kwargs["length_penalty"] = self._length_penalty
                kwargs["repetition_penalty"] = self._repetition_penalty
                kwargs["top_k"] = self._top_k
                kwargs["top_p"] = self._top_p
                kwargs["gpt_cond_len"] = self._gpt_cond_len
                kwargs["gpt_cond_chunk_len"] = min(self._gpt_cond_chunk_len, self._gpt_cond_len)
                kwargs["max_ref_len"] = self._max_ref_len
                kwargs["sound_norm_refs"] = self._sound_norm_refs

            while True:
                try:
                    engine.tts_to_file(**kwargs)
                    break
                except TypeError as exc:
                    match = re.search(r"unexpected keyword argument '([^']+)'", str(exc))
                    if not match:
                        raise
                    unsupported = match.group(1)
                    if unsupported not in kwargs:
                        raise
                    kwargs.pop(unsupported, None)
                    log_audit_entry(
                        "coqui_unsupported_tts_kwarg",
                        "[Coqui] Unsupported XTTS option was ignored.",
                        AuditStatus.WARNING,
                        details={"kwarg": unsupported},
                    )

            if not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
                raise TTSProviderError("Coqui did not create an audio file")

            source_wav_path, rvc_applied = self._apply_rvc_if_enabled(wav_path)
            cleanup_paths.add(source_wav_path)

            try:
                audio = AudioSegment.from_file(source_wav_path)
            except Exception as exc:
                if rvc_applied and source_wav_path != wav_path and os.path.exists(wav_path):
                    self._rvc_last_error = f"RVC output could not be decoded: {exc}"
                    log_audit_entry(
                        "coqui_rvc_decode_fallback",
                        "[Coqui] RVC output was invalid. Falling back to XTTS audio.",
                        AuditStatus.WARNING,
                        details={"error": str(exc)},
                    )
                    source_wav_path = wav_path
                    rvc_applied = False
                    audio = AudioSegment.from_file(source_wav_path)
                else:
                    raise
            if self._speed > 1.01:
                audio = audio.speedup(playback_speed=self._speed)
            elif self._speed < 0.99:
                audio = audio._spawn(
                    audio.raw_data,
                    overrides={"frame_rate": int(audio.frame_rate * self._speed)},
                ).set_frame_rate(audio.frame_rate)

            audio.export(output_path, format="mp3")

            duration_ms = int((time.time() - start) * 1000)
            return TTSResult(
                success=True,
                provider=self.name,
                file_path=output_path,
                duration_ms=duration_ms,
                details={"rvc_applied": rvc_applied},
            )
        except Exception as exc:
            raise TTSProviderError(f"Coqui synthesis failed: {exc}") from exc
        finally:
            for path in cleanup_paths:
                if not path or not os.path.exists(path):
                    continue
                try:
                    os.remove(path)
                except OSError:
                    pass

            if not self._keep_model_loaded:
                self.shutdown()
            elif self._low_ram_active() and self._engine is not None and engine is not None:
                self._move_engine_to_device(engine, "cpu")
                self._release_cuda_cache()

    def shutdown(self) -> None:
        with self._engine_lock:
            engine = self._engine
            self._engine = None

        if engine is None:
            return

        self._move_engine_to_device(engine, "cpu")

        try:
            del engine
        except Exception:
            pass

        try:
            from modules.tts.rvc.infer.infer import clear_runtime_cache

            clear_runtime_cache()
        except Exception:
            pass

        self._reset_rvc_runtime_state()
        self._preload_state = "idle" if self._preload_model else "disabled"

        self._release_cuda_cache()
