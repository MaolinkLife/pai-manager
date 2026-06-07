"""sherpa-onnx offline transcription engine.

Loaded lazily on the first use, cached at module scope (same lifecycle as the
faster-whisper model in stt.py — released by the existing should_release_resources
contract if/when wired into the lifecycle).

DB config sits at ``stt.sherpa_onnx.*`` and points at a directory containing
the model files. Sherpa publishes many recipes; we don't hard-code one, the
user provides paths explicitly:

  stt.sherpa_onnx.model_type        = "transducer" | "paraformer" | "whisper" | "moonshine"
  stt.sherpa_onnx.encoder           = "<path>/encoder.onnx"          (transducer)
  stt.sherpa_onnx.decoder           = "<path>/decoder.onnx"          (transducer)
  stt.sherpa_onnx.joiner            = "<path>/joiner.onnx"           (transducer)
  stt.sherpa_onnx.paraformer        = "<path>/model.onnx"            (paraformer)
  stt.sherpa_onnx.whisper_encoder   = "<path>/encoder.onnx"          (whisper)
  stt.sherpa_onnx.whisper_decoder   = "<path>/decoder.onnx"          (whisper)
  stt.sherpa_onnx.moonshine_preprocessor = "..."                     (moonshine)
  stt.sherpa_onnx.moonshine_encoder      = "..."
  stt.sherpa_onnx.moonshine_uncached_decoder = "..."
  stt.sherpa_onnx.moonshine_cached_decoder   = "..."
  stt.sherpa_onnx.tokens            = "<path>/tokens.txt"
  stt.sherpa_onnx.num_threads       = 1
  stt.sherpa_onnx.provider          = "cpu" | "cuda"

The transcribe() function accepts a wav file path, decodes it, and returns
the text. No streaming here — that's a separate feature with its own WS path.
"""

from __future__ import annotations

import wave
from typing import Any

import numpy as np

from modules.system import config as config_service
from modules.system.logger import AuditStatus, log_audit_entry


try:
    import sherpa_onnx as _sherpa
except Exception as _import_error:  # pragma: no cover
    _sherpa = None
    _SHERPA_IMPORT_ERROR = _import_error
else:
    _SHERPA_IMPORT_ERROR = None


_RECOGNIZER: Any = None
_RECOGNIZER_CFG_FINGERPRINT: tuple | None = None


class SherpaUnavailableError(RuntimeError):
    pass


def is_available() -> bool:
    return _sherpa is not None


def _get_settings() -> dict[str, Any]:
    cfg = config_service.get_config_value("stt.sherpa_onnx", {}) or {}
    if not isinstance(cfg, dict):
        cfg = {}
    return cfg


def _config_fingerprint(cfg: dict[str, Any]) -> tuple:
    """Tuple used to detect when settings changed and the recognizer must be rebuilt."""
    keys = (
        "model_type",
        "encoder",
        "decoder",
        "joiner",
        "paraformer",
        "whisper_encoder",
        "whisper_decoder",
        "moonshine_preprocessor",
        "moonshine_encoder",
        "moonshine_uncached_decoder",
        "moonshine_cached_decoder",
        "tokens",
        "num_threads",
        "provider",
    )
    return tuple((k, cfg.get(k)) for k in keys)


def _build_recognizer(cfg: dict[str, Any]):
    if _sherpa is None:
        raise SherpaUnavailableError(
            f"sherpa-onnx is not installed: {_SHERPA_IMPORT_ERROR!s}"
        )

    model_type = str(cfg.get("model_type") or "transducer").strip().lower()
    tokens = str(cfg.get("tokens") or "").strip()
    if not tokens:
        raise SherpaUnavailableError("stt.sherpa_onnx.tokens path is required.")
    num_threads = int(cfg.get("num_threads") or 1)
    provider = str(cfg.get("provider") or "cpu").strip().lower()

    if model_type == "transducer":
        encoder = str(cfg.get("encoder") or "").strip()
        decoder = str(cfg.get("decoder") or "").strip()
        joiner = str(cfg.get("joiner") or "").strip()
        if not (encoder and decoder and joiner):
            raise SherpaUnavailableError(
                "sherpa-onnx transducer requires encoder/decoder/joiner paths."
            )
        return _sherpa.OfflineRecognizer.from_transducer(
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            tokens=tokens,
            num_threads=num_threads,
            provider=provider,
        )

    if model_type == "paraformer":
        paraformer = str(cfg.get("paraformer") or "").strip()
        if not paraformer:
            raise SherpaUnavailableError("sherpa-onnx paraformer requires the model path.")
        return _sherpa.OfflineRecognizer.from_paraformer(
            paraformer=paraformer,
            tokens=tokens,
            num_threads=num_threads,
            provider=provider,
        )

    if model_type == "whisper":
        whisper_encoder = str(cfg.get("whisper_encoder") or "").strip()
        whisper_decoder = str(cfg.get("whisper_decoder") or "").strip()
        if not (whisper_encoder and whisper_decoder):
            raise SherpaUnavailableError(
                "sherpa-onnx whisper requires encoder/decoder paths."
            )
        return _sherpa.OfflineRecognizer.from_whisper(
            encoder=whisper_encoder,
            decoder=whisper_decoder,
            tokens=tokens,
            num_threads=num_threads,
            provider=provider,
        )

    if model_type == "moonshine":
        preprocessor = str(cfg.get("moonshine_preprocessor") or "").strip()
        encoder = str(cfg.get("moonshine_encoder") or "").strip()
        uncached = str(cfg.get("moonshine_uncached_decoder") or "").strip()
        cached = str(cfg.get("moonshine_cached_decoder") or "").strip()
        if not (preprocessor and encoder and uncached and cached):
            raise SherpaUnavailableError(
                "sherpa-onnx moonshine requires preprocessor/encoder/uncached/cached paths."
            )
        return _sherpa.OfflineRecognizer.from_moonshine(
            preprocessor=preprocessor,
            encoder=encoder,
            uncached_decoder=uncached,
            cached_decoder=cached,
            tokens=tokens,
            num_threads=num_threads,
            provider=provider,
        )

    raise SherpaUnavailableError(f"Unknown sherpa-onnx model_type: {model_type!r}")


def _get_recognizer():
    global _RECOGNIZER, _RECOGNIZER_CFG_FINGERPRINT
    cfg = _get_settings()
    fingerprint = _config_fingerprint(cfg)
    if _RECOGNIZER is not None and fingerprint == _RECOGNIZER_CFG_FINGERPRINT:
        return _RECOGNIZER
    recognizer = _build_recognizer(cfg)
    _RECOGNIZER = recognizer
    _RECOGNIZER_CFG_FINGERPRINT = fingerprint
    log_audit_entry(
        event_type="stt_sherpa_onnx_loaded",
        msg="[STT] sherpa-onnx recognizer loaded.",
        status=AuditStatus.INFO,
        details={"model_type": cfg.get("model_type"), "provider": cfg.get("provider")},
    )
    return recognizer


def release() -> None:
    """Drop the cached recognizer so the next call rebuilds with current config."""
    global _RECOGNIZER, _RECOGNIZER_CFG_FINGERPRINT
    _RECOGNIZER = None
    _RECOGNIZER_CFG_FINGERPRINT = None


def _read_wav_mono16k(path: str) -> tuple[np.ndarray, int]:
    """Return (float32 samples in [-1, 1], sample_rate). Mono mix-down if stereo."""
    with wave.open(path, "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        frames = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    elif sampwidth == 1:
        data = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise SherpaUnavailableError(f"Unsupported wav sample width: {sampwidth}")

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    return data.astype(np.float32, copy=False), sample_rate


def transcribe(file_path: str) -> str:
    """Synchronous file-based transcription. Raises SherpaUnavailableError on misconfig."""
    if _sherpa is None:
        raise SherpaUnavailableError(
            f"sherpa-onnx is not installed: {_SHERPA_IMPORT_ERROR!s}"
        )
    recognizer = _get_recognizer()
    samples, sample_rate = _read_wav_mono16k(file_path)
    stream = recognizer.create_stream()
    stream.accept_waveform(sample_rate, samples)
    recognizer.decode_stream(stream)
    return (stream.result.text or "").strip()
