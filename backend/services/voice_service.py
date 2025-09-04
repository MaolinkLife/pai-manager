import time
import os
import asyncio
import uuid
import numpy as np
import re
import emoji
import traceback
import threading
import io
import queue
import sounddevice as sd
import edge_tts

from pydub import AudioSegment
from services.config_service import get_config_value
from utils.sentence_splitter import split_into_sentences
from services.logger_service import log_error


# import utils.hotkeys
# import utils.zw_logging
# import utils.settings

assert os.name == "nt"

# ——— Settings ——— #
# VB_CABLE_OUTPUT_ID = 26
is_speaking = False
cut_voice = False

active_streams = []
stream_lock = threading.Lock()

tts_queue = queue.Queue()

AUDIO_TEMP_DIR = os.path.join(os.path.dirname(__file__), "..", "temp", "voice")
os.makedirs(AUDIO_TEMP_DIR, exist_ok=True)


def tts_worker():
    """Фоновый воркер: берёт (text, devices) и озвучивает"""
    while True:
        item = tts_queue.get()
        if item is None:
            break

        text, devices = item
        try:
            asyncio.run(stream_speak_line(text, devices))
        except Exception as e:
            print("[Voice Error]", e)
        finally:
            tts_queue.task_done()


# Removes all occurrences of the type *something*
def remove_emotions_or_actions(text: str) -> str:
    # Remove *actions* in asterisks
    text = re.sub(r"\*(.*?)\*", "", text).strip()

    # Remove emojis
    text = emoji.replace_emoji(text, replace="")

    return text


# ——— Main Functions ——— #
async def generate_tts(text, filename):
    voice = get_config_value(
        "voice.voice_language", "ru-RU-SvetlanaNeural"
    )  # Voice to play
    communicate = edge_tts.Communicate(text, voice=voice)
    await communicate.save(filename)


def play_voice_output(file_path):
    global active_streams

    if not os.path.isfile(file_path):
        print(f"[Voice Warning] File not found: {file_path}")
        return

    try:
        sound = AudioSegment.from_file(file_path)
        samples = np.array(sound.get_array_of_samples()).astype(np.float32)
        samples /= np.iinfo(sound.array_type).max

        streams_to_play = []

        # Проверяем, нужно ли воспроизводить на Windows
        if get_config_value("voice.use_windows_output", True):
            windows_output = get_config_value("voice.windows_output_id", 0)
            streams_to_play.append(windows_output)

        # Проверяем, нужно ли воспроизводить на VBCable
        if get_config_value("voice.use_rvc", False):
            virtual_output = get_config_value("voice.output_id", 0)
            streams_to_play.append(virtual_output)

        if not streams_to_play:
            print("[Voice Warning] No output devices enabled")
            return

        threads = []
        finished = threading.Event()

        def play_on_device(device_id):
            try:
                stream = sd.OutputStream(
                    samplerate=sound.frame_rate,
                    device=device_id,
                    channels=1 if samples.ndim == 1 else samples.shape[1],
                )
                with stream:
                    stream.start()
                    chunk_duration_sec = 0.1
                    chunk_size = int(sound.frame_rate * chunk_duration_sec)

                    i = 0
                    while i < len(samples):
                        if cut_voice:
                            print(f"[Voice] Playback interrupted on device {device_id}")
                            break
                        end = min(i + chunk_size, len(samples))
                        stream.write(samples[i:end])
                        i = end
                    stream.stop()

            except Exception as e:
                print(f"[Voice Error] Failed to play on device {device_id}: {e}")
            finally:
                finished.set()

        # Запускаем воспроизведение на всех устройствах
        for device_id in streams_to_play:
            t = threading.Thread(target=play_on_device, args=(device_id,))
            t.daemon = True
            t.start()
            threads.append(t)

        # Ждём окончания всех устройств (чтобы чанк играл синхронно на обоих)
        for t in threads:
            t.join()

    except Exception as e:
        print(f"[Voice Error] Failed to load audio file: {e}")


def speak_line(s_message, refuse_pause):
    global cut_voice
    cut_voice = False
    set_speaking(True)

    chunky_message = split_into_sentences(s_message)
    print(f"[Voice] Got {len(chunky_message)} chunks to speak")

    for i, chunk in enumerate(chunky_message):
        print(f"[Voice] Processing chunk {i+1}/{len(chunky_message)}: {chunk[:30]}...")

        # Убираем проверку в начале - пусть хотя бы этот чанк озвучит
        # if cut_voice:
        #     break

        try:
            clean_chunk = remove_emotions_or_actions(chunk)
            if not clean_chunk.strip():
                continue

            filename = os.path.join(AUDIO_TEMP_DIR, f"tts_output_{uuid.uuid4()}.mp3")
            print(f"[Voice] Generating TTS for chunk {i+1}")
            asyncio.run(generate_tts(clean_chunk, filename))

            print(f"[Voice] Playing chunk {i+1}")
            play_voice_output(filename)  # ← Вот тут может быть прервано

            if os.path.exists(filename):
                os.remove(filename)

            # Проверяем после воспроизведения
            if cut_voice:
                print(f"[Voice] Interrupted after chunk {i+1}")
                break

            time.sleep(0.01 if not refuse_pause else 0.001)

        except Exception as e:
            log_error("[Voice Error]", context=traceback.format_exc())
            if cut_voice:
                break

    set_speaking(False)
    print("[Voice] Finished speaking")


# ===========================================================
# Streaming TTS (новый метод, без файлов и чанков)
# ===========================================================
async def stream_speak_line(text: str, devices: list[int]):
    global cut_voice, active_streams
    cut_voice = False

    voice = get_config_value("voice.voice_language", "ru-RU-SvetlanaNeural")
    communicate = edge_tts.Communicate(text, voice=voice)

    streams = []
    for device_id in devices:
        stream = sd.OutputStream(
            samplerate=24000,
            channels=1,
            dtype="float32",  # будем конвертировать в float32
            device=device_id,
        )
        stream.start()
        streams.append(stream)

    with stream_lock:
        active_streams = streams.copy()

    buffer = io.BytesIO()

    try:
        async for chunk in communicate.stream():
            if cut_voice:
                break

            if chunk["type"] == "audio":
                buffer.write(chunk["data"])

                # Пробуем декодировать, если накопилось достаточно
                if buffer.tell() > 8192:  # 8 KB ~ маленький кусок mp3
                    buffer.seek(0)
                    try:
                        segment = AudioSegment.from_file(buffer, format="mp3")
                        samples = np.array(segment.get_array_of_samples()).astype(
                            np.float32
                        )
                        samples /= np.iinfo(segment.array_type).max
                        for stream in streams:
                            stream.write(samples)
                    except Exception:
                        pass
                    buffer = io.BytesIO()  # очищаем и начинаем копить заново
    finally:
        for s in streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        with stream_lock:
            active_streams.clear()
        set_speaking(False)
        print("[Voice] Streaming finished")


# ——— STATUS FLAGS ——— #
def check_if_speaking() -> bool:
    return is_speaking


def set_speaking(set: bool):
    global is_speaking
    is_speaking = set


def force_cut_voice():
    global cut_voice, active_streams

    cut_voice = True

    # Останавливаем все активные потоки
    with stream_lock:
        if active_streams:
            sd.stop()  # Останавливаем все потоки sounddevice
            active_streams.clear()

    print("[Voice] All streams stopped")
