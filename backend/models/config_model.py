# ===========================================================
# Module: config_model.py
# Purpose: Configuration data models and default values
# Used in: config_service.py, API routes, validation
# ===========================================================

from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union


class VoiceConfig(BaseModel):
    enabled: bool = True
    output_id: int = 25
    windows_output_id: int = 12
    language: str = "ru-RU"
    use_rvc: bool = True
    voice_language: str = "ru-RU-SvetlanaNeural"
    use_windows_output: bool = True
    streaming_tts: bool = False


class ModulesConfig(BaseModel):
    vtube_studio: bool = True
    whisper: bool = True
    minecraft: bool = False
    gaming: bool = False
    alarm: bool = False
    discord: bool = False
    rag: bool = True
    visual: bool = True


class AudioConfig(BaseModel):
    inputDeviceId: int = 0
    sampleRate: int = 16000
    channels: int = 1
    chunkSize: int = 1024
    enableVad: bool = True
    vadThreshold: float = 0.5
    silenceTimeout: float = 3.0
    minAudioLength: float = 0.5
    maxAudioLength: float = 30.0
    triggerWords: List[str] = []


class VisionConfig(BaseModel):
    enabled: bool = True
    monitor_index: int = 1
    fps: int = 5
    buffer_sec: int = 4
    downscale_width: int = 1280
    yolo_enabled: bool = True
    ocr_lang: str = "rus+eng"
    ocr_min_conf: int = 70
    ocr_max_lines: int = 5
    region: Optional[Any] = None


class RAGSearchStrategySessionContext(BaseModel):
    enabled: bool = True
    maxMessages: int = 32
    lookBackToToday: bool = True


class RAGSearchStrategyDailySummary(BaseModel):
    enabled: bool = True
    lookBackDays: int = 7
    useTags: bool = True


class RAGSearchStrategyLongTermMemory(BaseModel):
    enabled: bool = True
    vectorSearch: bool = True
    graphSearch: bool = True
    priorityRules: bool = True


class RAGSearchStrategyFallback(BaseModel):
    askUser: bool = True
    autoLearn: bool = True


class RAGSearchStrategy(BaseModel):
    sessionContext: RAGSearchStrategySessionContext = RAGSearchStrategySessionContext()
    dailySummary: RAGSearchStrategyDailySummary = RAGSearchStrategyDailySummary()
    longTermMemory: RAGSearchStrategyLongTermMemory = RAGSearchStrategyLongTermMemory()
    fallback: RAGSearchStrategyFallback = RAGSearchStrategyFallback()


class RAGMemoryFacts(BaseModel):
    enabled: bool = True
    priorityRules: List[str] = ["user", "name", "person"]
    autoUpdate: bool = True


class RAGMemoryGraph(BaseModel):
    enabled: bool = True
    relationships: bool = True
    inference: bool = True


class RAGMemory(BaseModel):
    facts: RAGMemoryFacts = RAGMemoryFacts()
    graph: RAGMemoryGraph = RAGMemoryGraph()


class RAGConfig(BaseModel):
    enabled: bool = True
    embeddingModel: str = "all-MiniLM-L6-v2"
    vectorDbPath: str = "./data/vector_db"
    chunkSize: int = 500
    chunkOverlap: int = 50
    topK: int = 5
    similarityThreshold: float = 0.7
    enableCaching: bool = True
    cacheTtl: int = 60
    searchStrategy: RAGSearchStrategy = RAGSearchStrategy()
    memory: RAGMemory = RAGMemory()


class OpenRouterConfig(BaseModel):
    api_key: str = "sk-***"
    model: str = "deepseek/deepseek-chat-v3.1:free"


class APIConfig(BaseModel):
    type: str = "Ollama"
    streaming: bool = True
    model: str = "gpt-oss:20b"
    visual_model: str = "apple/FastVLM-1.5B"
    token_limit: int = 4096
    message_pair_limit: int = 10


class GenerateSettingsConfig(BaseModel):
    name: str = "Default"
    description: str = "Basic generation parameters"
    temperature: float = 0.85
    min_p: float = 0.05
    top_p: float = 0.9
    top_k: int = 70
    repeat_penalty: float = 1.2
    stop: Optional[Any] = None
    num_predict: int = 2048


class AppConfig(BaseModel):
    user_id: Optional[str] = None
    char_name: str = "Lim"
    user_name: str = "Mao"
    language: str = "ru-RU"
    voice: VoiceConfig = VoiceConfig()
    modules: ModulesConfig = ModulesConfig()
    audio: AudioConfig = AudioConfig()
    vision: VisionConfig = VisionConfig()
    rag: RAGConfig = RAGConfig()
    openrouter: OpenRouterConfig = OpenRouterConfig()
    api: APIConfig = APIConfig()
    generate_settings: GenerateSettingsConfig = GenerateSettingsConfig()

    class Config:
        # Allow arbitrary non-primitive field types
        arbitrary_types_allowed = True


# Default configuration as dict (for backward compatibility)
DEFAULT_CONFIG = AppConfig().dict()

# Configuration paths for easy access
CONFIG_PATHS = {
    "config": "config/config.json",
    "presets": "config/generation_presets.json",
}
