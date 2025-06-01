import sounddevice as sd
import numpy as np
import tempfile
import os
import wave
from faster_whisper import WhisperModel


# Параметры записи
SAMPLE_RATE = 16000
CHANNELS = 1
DURATION = 5  # секунд

# Инициализация модели один раз
model = WhisperModel("base", device="cpu", compute_type="int8")


def record_audio(filename: str, duration: int = DURATION):
    print(f"[🎙] Recording for {duration} seconds...")
    audio = sd.rec(int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=CHANNELS, dtype='int16')
    sd.wait()

    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(audio.tobytes())

    print(f"[💾] Saved audio to: {filename}")


def transcribe_audio(filename: str) -> str:
    print(f"[🔍] Transcribing: {filename}")
    segments, _ = model.transcribe(filename)
    result = " ".join(segment.text for segment in segments)
    print(f"[📜] Transcribed text: {result}")
    return result


def record_and_transcribe() -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
    record_audio(path)
    result = transcribe_audio(path)
    os.remove(path)
    return result
