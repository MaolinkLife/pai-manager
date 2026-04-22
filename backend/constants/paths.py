import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
CONFIG_DIR = os.path.join(BASE_DIR, "config")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TRACEBACK_LOGS_DIR = os.path.join(PROJECT_DIR, "logs")
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
TEMP_DIR = os.path.join(BASE_DIR, "temp")

MODELS_DIR = os.path.join(STORAGE_DIR, "models")
RVC_MODELS_DIR = os.path.join(MODELS_DIR, "rvc")
VISION_MODELS_DIR = os.path.join(MODELS_DIR, "vision")
GENERATION_MODELS_DIR = os.path.join(MODELS_DIR, "generation")
TTS_MODELS_DIR = os.path.join(MODELS_DIR, "tts")
STT_MODELS_DIR = os.path.join(MODELS_DIR, "stt")
GGUF_MODELS_DIR = os.path.join(MODELS_DIR, "gguf")
DIFFUSER_MODELS_DIR = os.path.join(MODELS_DIR, "diffuser")

MODEL_SUBDIRS = (
    RVC_MODELS_DIR,
    VISION_MODELS_DIR,
    GENERATION_MODELS_DIR,
    TTS_MODELS_DIR,
    STT_MODELS_DIR,
    GGUF_MODELS_DIR,
    DIFFUSER_MODELS_DIR,
    os.path.join(GENERATION_MODELS_DIR, "image"),
    os.path.join(GENERATION_MODELS_DIR, "video"),
    os.path.join(GENERATION_MODELS_DIR, "audio"),
)
