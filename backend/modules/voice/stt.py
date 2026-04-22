import os
import tempfile
import warnings
import wave
from typing import Any

import numpy as np
import sounddevice as sd

from constants.paths import STT_MODELS_DIR
from modules.system import config as config_service

warnings.filterwarnings(
    "ignore",
    message=r"pkg_resources is deprecated as an API\.",
    category=UserWarning,
    module=r"ctranslate2(\..*)?$",
)

try:
    from faster_whisper import WhisperModel as _WhisperModel
except Exception as _stt_import_error:  # pragma: no cover
    _WhisperModel = None
    _WHISPER_IMPORT_ERROR = _stt_import_error
else:
    _WHISPER_IMPORT_ERROR = None

_stream = None
_buffer = []
_is_recording = False

SAMPLE_RATE = 16000
CHANNELS = 1
os.makedirs(STT_MODELS_DIR, exist_ok=True)
_MODEL: Any = None


def _get_model() -> Any:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    if _WhisperModel is None:
        details = f"{_WHISPER_IMPORT_ERROR}" if _WHISPER_IMPORT_ERROR else "unknown import error"
        raise RuntimeError(
            "faster-whisper is unavailable in current environment. "
            "Check Python dependencies (setuptools<81 is required for current ctranslate2 builds). "
            f"Details: {details}"
        )

    model_name = config_service.get_config_value("stt.model", "base") or "base"
    device = config_service.get_config_value("stt.device", "cpu") or "cpu"
    compute_type = config_service.get_config_value("stt.compute_type", "int8") or "int8"

    _MODEL = _WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        download_root=STT_MODELS_DIR,
    )
    return _MODEL


def record_audio(filename: str, duration: int = 5):
    audio = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
    )
    sd.wait()
    _save_wave(filename, audio)


def transcribe_audio(filename: str) -> str:
    model = _get_model()
    stt_lang = config_service.get_config_value("stt.language", None)
    auto_detect = config_service.get_config_value("stt.auto_detect", True)

    if auto_detect or not stt_lang:
        segments, _ = model.transcribe(filename)
    else:
        lang_code = stt_lang.split("-")[0]
        segments, _ = model.transcribe(filename, language=lang_code)

    result = " ".join(segment.text for segment in segments)
    return result


def record_and_transcribe() -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
    record_audio(path)
    result = transcribe_audio(path)
    os.remove(path)
    return result


def start_recording_background(filename: str):
    global _stream, _buffer, _is_recording

    if _is_recording:
        return

    os.makedirs(os.path.dirname(filename), exist_ok=True)

    _buffer = []
    _is_recording = True

    def callback(indata, frames, time, status):
        if _is_recording:
            _buffer.append(indata.copy())

    _stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16", callback=callback
    )
    _stream.start()


def stop_recording_and_save(filename: str):
    global _stream, _is_recording, _buffer

    if not _is_recording:
        raise RuntimeError("Recording is not active - stopping is not possible.")

    _is_recording = False

    if _stream:
        _stream.stop()
        _stream.close()
        _stream = None

    if not _buffer:
        raise RuntimeError("The buffer is empty. Nothing written.")

    audio = np.concatenate(_buffer, axis=0)
    _save_wave(filename, audio)
    _buffer.clear()


def _save_wave(filename: str, audio: np.ndarray):
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())


def is_recording() -> bool:
    return _is_recording


def get_recording_state():
    return {
        "recording": _is_recording,
        "stream": _stream is not None,
        "buffer_size": len(_buffer),
    }
