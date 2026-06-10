"""Qwen-TTS provider via the faster-qwen3-tts package.

In-process synth — same lifecycle as the existing Coqui provider rather than
AI_WAIFU_Y's separate subprocess worker. The pai-manager TTS manager already
runs CoquiTTSProvider in-process and handles GPU memory through the existing
should_release_resources contract, so we do not need a new IPC layer.

Weights are downloaded by HuggingFace Hub on first load. We pin the cache
location to ``TTS_MODELS_DIR/qwen`` (gitignored) so models do not scatter into
the user's global HF cache.

DB config: ``voice.voice_modules.qwen``. Disabled until the user selects it
via ``voice.active_module = "qwen"``; ``is_available()`` reflects the package
import status, so a missing torch/CUDA still surfaces cleanly through the
fallback chain.
"""

from __future__ import annotations

import os
import threading
import wave
from typing import Any, Dict, Optional, Tuple

import numpy as np

from constants.paths import TTS_MODELS_DIR
from modules.system.logger import AuditStatus, log_audit_entry

from .base import TTSProvider, TTSProviderError, TTSRequest, TTSResult


try:
    import faster_qwen3_tts as _fq
except Exception as _import_error:  # pragma: no cover
    _fq = None
    _QWEN_IMPORT_ERROR = _import_error
else:
    _QWEN_IMPORT_ERROR = None


_DEFAULT_MODEL_NAME = "Qwen/Qwen3-TTS-Flash"
_DEFAULT_LANGUAGE = "English"
_QWEN_CACHE_DIR = os.path.join(TTS_MODELS_DIR, "qwen")


def _ensure_cache_dir_env() -> None:
    """Make HF use the project's TTS storage instead of the user-wide cache."""
    os.makedirs(_QWEN_CACHE_DIR, exist_ok=True)
    # Only set what isn't already set — never override an explicit user env.
    os.environ.setdefault("HF_HOME", _QWEN_CACHE_DIR)
    os.environ.setdefault("HUGGINGFACE_HUB_CACHE", _QWEN_CACHE_DIR)


def _resolve_dtype(name: str):
    import torch

    mapping = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "fp16": torch.float16,
        "float32": torch.float32,
        "fp32": torch.float32,
    }
    return mapping.get(name.strip().lower(), torch.bfloat16)


def _save_wav(path: str, audio: np.ndarray, sample_rate: int) -> None:
    """Write float audio in [-1,1] as 16-bit PCM."""
    samples = np.asarray(audio).squeeze()
    if samples.ndim > 1:
        samples = samples.mean(axis=0)
    samples = np.clip(samples, -1.0, 1.0)
    int16 = (samples * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(int16.tobytes())


class QwenTTSProvider(TTSProvider):
    """faster-qwen3-tts adapter.

    The model is loaded lazily on the first synthesize call. ``shutdown()``
    drops the cached model and clears the CUDA cache so the existing
    should_release_resources contract can keep memory under control.
    """

    def __init__(self, cfg: Optional[Dict[str, Any]] = None) -> None:
        self._cfg = dict(cfg or {})
        self._name = "qwen"
        self._model: Any = None
        self._sample_rate: int | None = None
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        return self._name

    def is_available(self) -> bool:
        return _fq is not None

    # ------------------------------------------------------------------
    # config
    # ------------------------------------------------------------------

    def _resolve_cfg(self, request: TTSRequest) -> Dict[str, Any]:
        # Fresh read on each call so DB updates take effect without a manager
        # restart. The model is only rebuilt when load-time fields change.
        from modules.system import config as config_service

        cfg = config_service.get_config_value("voice.voice_modules.qwen", {}) or {}
        if not isinstance(cfg, dict):
            cfg = {}
        merged = {**self._cfg, **cfg}

        # Per-request overrides go on top.
        if request.language and request.language != "auto":
            merged["language"] = request.language
        if request.voice:
            merged["voice"] = request.voice
        return merged

    def _get_model(self, cfg: Dict[str, Any]):
        if _fq is None:
            raise TTSProviderError(
                f"faster-qwen3-tts is not installed: {_QWEN_IMPORT_ERROR!s}"
            )
        if self._model is not None:
            return self._model

        with self._lock:
            if self._model is not None:
                return self._model

            _ensure_cache_dir_env()
            model_name = str(cfg.get("model_name") or _DEFAULT_MODEL_NAME)
            device = str(cfg.get("device") or "cuda")
            dtype = _resolve_dtype(str(cfg.get("dtype") or "bfloat16"))
            max_seq_len = int(cfg.get("max_seq_len") or 2048)

            log_audit_entry(
                "tts_qwen_load",
                "[TTS] Loading Qwen-TTS.",
                AuditStatus.INFO,
                details={"model": model_name, "device": device, "dtype": str(dtype)},
            )
            try:
                self._model = _fq.FasterQwen3TTS.from_pretrained(
                    model_name=model_name,
                    device=device,
                    dtype=dtype,
                    max_seq_len=max_seq_len,
                )
            except Exception as exc:
                raise TTSProviderError(f"Qwen-TTS load failed: {exc}") from exc

        return self._model

    # ------------------------------------------------------------------
    # synthesize
    # ------------------------------------------------------------------

    def synthesize(self, request: TTSRequest, output_path: str) -> TTSResult:
        cfg = self._resolve_cfg(request)
        if not request.text or not request.text.strip():
            raise TTSProviderError("Qwen-TTS: empty text.")

        model = self._get_model(cfg)
        try:
            audio, sample_rate = self._call_generate(model, request.text, cfg)
        except TTSProviderError:
            raise
        except Exception as exc:
            raise TTSProviderError(f"Qwen-TTS synthesis error: {exc}") from exc

        try:
            _save_wav(output_path, audio, sample_rate)
        except Exception as exc:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass
            raise TTSProviderError(f"Qwen-TTS file write error: {exc}") from exc

        if not (os.path.exists(output_path) and os.path.getsize(output_path) > 0):
            raise TTSProviderError("Qwen-TTS produced no output.")

        self._sample_rate = sample_rate
        return TTSResult(
            success=True,
            file_path=output_path,
            provider=self.name,
            details={"sample_rate": sample_rate, "language": cfg.get("language")},
        )

    @staticmethod
    def _call_generate(model: Any, text: str, cfg: Dict[str, Any]) -> Tuple[Any, int]:
        kwargs = {
            "text": text,
            "language": str(cfg.get("language") or _DEFAULT_LANGUAGE),
        }
        # Tunables — only forward when present so package defaults stay intact.
        for key in ("max_new_tokens", "temperature", "top_k", "repetition_penalty", "do_sample"):
            if key in cfg and cfg[key] is not None:
                kwargs[key] = cfg[key]
        audio, sample_rate = model.generate(**kwargs)
        return audio, int(sample_rate)

    # ------------------------------------------------------------------
    # shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._model is None:
            return
        try:
            del self._model
        except Exception:
            pass
        self._model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        log_audit_entry(
            "tts_qwen_unloaded",
            "[TTS] Qwen-TTS released.",
            AuditStatus.INFO,
        )
