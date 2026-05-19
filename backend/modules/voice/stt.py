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


class AudioInputUnavailableError(RuntimeError):
    pass


class NoAudioCapturedError(RuntimeError):
    pass


class TranscriptionRejectedError(RuntimeError):
    pass


def _resolve_input_device_id() -> int:
    raw_device_id = config_service.get_config_value("audio.input_device_id", 0)
    try:
        device_id = int(raw_device_id)
    except (TypeError, ValueError) as exc:
        raise AudioInputUnavailableError(
            f"Audio input device id is invalid: {raw_device_id!r}"
        ) from exc

    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise AudioInputUnavailableError(f"Audio input is unavailable: {exc}") from exc

    input_ids = [
        index
        for index, device in enumerate(devices)
        if int(device.get("max_input_channels", 0) or 0) > 0
    ]
    if not input_ids:
        raise AudioInputUnavailableError("Audio input is unavailable: no input devices found.")
    if device_id not in input_ids:
        raise AudioInputUnavailableError(
            f"Audio input device {device_id} is unavailable."
        )
    return device_id


def _is_audio_too_quiet(audio: np.ndarray) -> bool:
    if audio.size == 0:
        return True
    min_length = float(config_service.get_config_value("audio.min_audio_length", 0.5) or 0.5)
    duration = audio.shape[0] / float(SAMPLE_RATE)
    if duration < min_length:
        return True

    normalized = audio.astype(np.float32)
    peak = float(np.max(np.abs(normalized)))
    rms = float(np.sqrt(np.mean(np.square(normalized))))
    peak_threshold = float(
        config_service.get_config_value("audio.min_recording_peak", 150) or 150
    )
    rms_threshold = float(
        config_service.get_config_value("audio.min_recording_rms", 35) or 35
    )
    return peak < peak_threshold and rms < rms_threshold


def _is_rejected_transcript(text: str) -> bool:
    normalized = " ".join((text or "").split()).strip().lower()
    if not normalized:
        return True
    rejected_phrases = {
        "редактор субтитров а.синецкая корректор а.егорова",
        "редактор субтитров а синецкая корректор а егорова",
    }
    return normalized in rejected_phrases


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
    device_id = _resolve_input_device_id()
    audio = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype="int16",
        device=device_id,
    )
    sd.wait()
    if _is_audio_too_quiet(audio):
        raise NoAudioCapturedError("No audio input detected.")
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

    result = " ".join(segment.text for segment in segments).strip()
    if _is_rejected_transcript(result):
        raise TranscriptionRejectedError("No valid speech detected.")
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
    device_id = _resolve_input_device_id()

    _buffer = []

    def callback(indata, frames, time, status):
        if _is_recording:
            _buffer.append(indata.copy())

    try:
        _stream = sd.InputStream(
            device=device_id,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            callback=callback,
        )
        _stream.start()
    except Exception as exc:
        _stream = None
        _buffer = []
        _is_recording = False
        raise AudioInputUnavailableError(f"Audio input is unavailable: {exc}") from exc

    _is_recording = True


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
        raise NoAudioCapturedError("No audio input detected.")

    audio = np.concatenate(_buffer, axis=0)
    _buffer.clear()
    if _is_audio_too_quiet(audio):
        raise NoAudioCapturedError("No speech detected.")

    _save_wave(filename, audio)


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
