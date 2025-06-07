import sounddevice as sd
import numpy as np
import tempfile
import os
import wave
from faster_whisper import WhisperModel

# ===============================
# СТАТУСНЫЕ ПЕРЕМЕННЫЕ
# ===============================
_stream = None
_buffer = []
_is_recording = False

# ===============================
# КОНСТАНТЫ
# ===============================
SAMPLE_RATE = 16000
CHANNELS = 1
MODEL = WhisperModel("base", device="cpu", compute_type="int8")


# ===============================
# ЗАПИСЬ СИНХРОННАЯ
# ===============================
def record_audio(filename: str, duration: int = 5):
    print(f"[🎙] Recording for {duration} seconds...")
    audio = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16')
    sd.wait()

    _save_wave(filename, audio)
    print(f"[💾] Saved audio to: {filename}")


# ===============================
# ТРАНСКРИПЦИЯ
# ===============================
def transcribe_audio(filename: str) -> str:
    print(f"[🔍] Transcribing: {filename}")
    segments, _ = MODEL.transcribe(filename)
    result = " ".join(segment.text for segment in segments)
    print(f"[📜] Transcribed text: {result}")
    return result


# ===============================
# ЗАПИСЬ + ТРАНСКРИПЦИЯ
# ===============================
def record_and_transcribe() -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
    record_audio(path)
    result = transcribe_audio(path)
    os.remove(path)
    return result


# ===============================
# ЗАПИСЬ В ФОНЕ
# ===============================
def start_recording_background(filename: str):
    global _stream, _buffer, _is_recording

    if _is_recording:
        print("[⚠] Запись уже идёт.")
        return

    os.makedirs(os.path.dirname(filename), exist_ok=True)

    _buffer = []
    _is_recording = True

    def callback(indata, frames, time, status):
        if status:
            print(f"[⚠] Статус записи: {status}")
        if _is_recording:
            _buffer.append(indata.copy())

    _stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        dtype='int16',
        callback=callback
    )
    _stream.start()
    print("[🎙] Фоновая запись началась...")


# ===============================
# СТОП + СОХРАНЕНИЕ WAV
# ===============================
def stop_recording_and_save(filename: str):
    global _stream, _is_recording, _buffer

    if not _is_recording:
        raise RuntimeError("Запись не активна — остановка невозможна.")

    _is_recording = False

    if _stream:
        _stream.stop()
        _stream.close()
        _stream = None

    if not _buffer:
        raise RuntimeError("Буфер пуст. Ничего не записано.")

    audio = np.concatenate(_buffer, axis=0)
    _save_wave(filename, audio)
    _buffer.clear()

    print(f"[💾] Аудио сохранено: {filename}")


# ===============================
# УТИЛИТА СОХРАНЕНИЯ WAV
# ===============================
def _save_wave(filename: str, audio: np.ndarray):
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)  # int16 → 2 байта
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())


# ===============================
# ФЛАГ: ИДЁТ ЛИ ЗАПИСЬ
# ===============================
def is_recording() -> bool:
    return _is_recording


# ===============================
# ОТЛАДКА: СОСТОЯНИЕ
# ===============================
def get_recording_state():
    return {
        "recording": _is_recording,
        "stream": _stream is not None,
        "buffer_size": len(_buffer)
    }
