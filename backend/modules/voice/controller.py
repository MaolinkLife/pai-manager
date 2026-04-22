import os
import uuid
from datetime import datetime, timezone

from constants.paths import TEMP_DIR
from modules.voice import stt as stt_service

TEMP_AUDIO_PATH = os.path.join(TEMP_DIR, "voice", "temp_recording.wav")


def start_recording():
    os.makedirs(os.path.dirname(TEMP_AUDIO_PATH), exist_ok=True)
    stt_service.start_recording_background(TEMP_AUDIO_PATH)
    return {"status": "ok", "message": "Запись началась."}


def stop_recording_and_process(character_name: str) -> dict:
    stt_service.stop_recording_and_save(TEMP_AUDIO_PATH)
    transcript = stt_service.transcribe_audio(TEMP_AUDIO_PATH)

    message_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)

    if os.path.exists(TEMP_AUDIO_PATH):
        os.remove(TEMP_AUDIO_PATH)

    return {
        "id": message_id,
        "role": "user",
        "content": transcript,
        "timestamp": timestamp.isoformat(),
    }
