# ===========================================================
# Module: config_model.py
# Purpose: Configuration data models and default values
# Used in: config_service.py, API routes, validation
# ===========================================================

from constants.settings import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_TEMPERATURE,
    OPENROUTER_BASE_URL,
)
from constants.prompts import (
    COGNITIVE_ANALYSIS_PROMPT,
    INSTRUCTOR_BUILD_SCHEMA_PROMPT,
    MORAL_MATRIX_PROVIDER_PROMPT,
)
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ---------------------------
# New: System + Core configs
# ---------------------------
class SystemConfig(BaseModel):
    user_id: Optional[str] = None
    user_name: str = "You"
    char_name: str = "Character Name"
    language: str = "en-US"
    system_prompt: str = ""  # будет подтягиваться из characters/{char_name}.yaml
    theme: str = "default"
    # HTTP/WS access policy. "tunnel_aware" (default) = loopback + active tunnel public_url;
    # "strict_local" = loopback only (even with active tunnel); "open" = no host/origin checks.
    api_access_mode: str = "tunnel_aware"
    runtime: Dict[str, Any] = Field(
        default_factory=lambda: {
            "model_memory_profile": "low_memory_strict",
        }
    )


class CoreConfig(BaseModel):
    version: str = "1.0.0"
    env: str = "dev"
    debug: bool = False


class DecisionLayerCapabilitiesConfig(BaseModel):
    tool: bool = False
    vision: bool = False
    thinking: bool = False


class DecisionLayerProviderOllamaConfig(BaseModel):
    model: str = "llama3.2"
    temperature: float = 0.2
    max_tokens: int = 512
    thinking: bool = False


class DecisionLayerProvidersConfig(BaseModel):
    ollama: DecisionLayerProviderOllamaConfig = DecisionLayerProviderOllamaConfig()


class DecisionLayerInstructorConfig(BaseModel):
    build_schema: str = INSTRUCTOR_BUILD_SCHEMA_PROMPT
    include_datetime: bool = True
    include_geolocation: bool = False
    exclude_disabled_modules: bool = True


class DecisionLayerConfig(BaseModel):
    mode: str = "system"
    active_provider: str = "ollama"
    max_steps: int = 4
    release_after_use: bool = True
    capabilities: DecisionLayerCapabilitiesConfig = DecisionLayerCapabilitiesConfig()
    providers: DecisionLayerProvidersConfig = DecisionLayerProvidersConfig()
    instructor: DecisionLayerInstructorConfig = DecisionLayerInstructorConfig()


class ConnectorTunnelingConfig(BaseModel):
    enabled: bool = False
    provider: str = "cloudflared"
    local_url: str = "http://127.0.0.1:3880"
    local_port: int = 3880
    command_path: str = ""
    public_url: str = ""


class ConnectorConfig(BaseModel):
    tunneling: ConnectorTunnelingConfig = ConnectorTunnelingConfig()


class VoiceModulesElevenLabsConfig(BaseModel):
    api_key: str = ""
    voice_id: str = ""
    model_id: str = ""
    stability: float = 0.5
    similarity: float = 0.75


class VoiceModulesEdgeConfig(BaseModel):
    voice_language: str = "en-US-JennyNeural"


class VoiceConfig(BaseModel):
    enabled: bool = True
    output_id: int = 0
    windows_output_id: int = 0
    language: str = "en-US"
    use_rvc: bool = False
    use_windows_output: bool = False
    streaming_tts: bool = False
    enable_fallback: bool = True
    active_module: str = "edge"
    voice_modules: Dict[str, Any] = {
        "elevenlabs": {
            "api_key": "",
            "voice_id": "",
            "model_id": "",
            "stability": 0.5,
            "similarity": 0.75,
        },
        "edge": {"voice_language": "en-US-JennyNeural"},
        "qwen": {
            "model_name": "Qwen/Qwen3-TTS-Flash",
            "device": "cuda",
            "dtype": "bfloat16",
            "max_seq_len": 2048,
            "language": "English",
            "temperature": 0.9,
            "top_k": 50,
            "repetition_penalty": 1.05,
            "max_new_tokens": 2048,
            "do_sample": True,
        },
    }
    voice_language: str = "en-US-JennyNeural"


class STTSherpaOnnxConfig(BaseModel):
    model_type: str = "transducer"
    encoder: str = ""
    decoder: str = ""
    joiner: str = ""
    paraformer: str = ""
    whisper_encoder: str = ""
    whisper_decoder: str = ""
    moonshine_preprocessor: str = ""
    moonshine_encoder: str = ""
    moonshine_uncached_decoder: str = ""
    moonshine_cached_decoder: str = ""
    tokens: str = ""
    num_threads: int = 1
    provider: str = "cpu"


class STTConfig(BaseModel):
    language: str = "en-US"
    auto_detect: bool = False
    provider: str = "whisper"
    sherpa_onnx: STTSherpaOnnxConfig = STTSherpaOnnxConfig()


class ModulesConfig(BaseModel):
    vtube_studio: bool = False
    whisper: bool = True
    minecraft: bool = False
    gaming: bool = False
    alarm: bool = False
    discord: bool = False
    telegram: bool = False
    rag: bool = True
    visual: bool = True


class CommunicationChannelConfig(BaseModel):
    enabled: bool = True
    allow_fallback: bool = False


class CommunicationChannelsConfig(BaseModel):
    main_chat: CommunicationChannelConfig = CommunicationChannelConfig(
        enabled=True,
        allow_fallback=False,
    )
    telegram: CommunicationChannelConfig = CommunicationChannelConfig(
        enabled=True,
        allow_fallback=False,
    )


class CommunicationConfig(BaseModel):
    priority: List[str] = Field(default_factory=lambda: ["main_chat", "telegram"])
    channels: CommunicationChannelsConfig = CommunicationChannelsConfig()


class AudioConfig(BaseModel):
    input_device_id: int = 0
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    enable_vad: bool = True
    vad_threshold: float = 0.5
    silence_timeout: float = 3.0
    min_audio_length: float = 0.5
    max_audio_length: float = 120.0
    trigger_words: List[str] = []
    ignore_trigger_words: bool = True


class VisionModulesAppleVisionConfig(BaseModel):
    model_id: str = "apple/FastVLM-1.5B"
    max_tokens: int = 128


class VisionModulesLlavaConfig(BaseModel):
    model_id: str = "llava-hf/llava-1.5-7b-hf"
    max_tokens: int = 128


class VisionConfig(BaseModel):
    enabled: bool = True
    active_provider: str = "apple_vision"
    monitor_index: int = 0
    fps: int = 5
    buffer_sec: int = 4
    downscale_width: int = 1280
    yolo_enabled: bool = False
    ocr_lang: str = "eng"
    ocr_min_conf: int = 70
    ocr_max_lines: int = 5
    region: Optional[Any] = None
    capture_mode: str = "monitor"
    window_title: str = ""
    window_process: str = ""
    debug_save: bool = False
    debug_path: str = "temp/vision"
    vision_modules: Dict[str, Any] = {
        "apple_vision": {"model_id": "apple/FastVLM-1.5B", "max_tokens": 128},
        "llava": {"model_id": "llava-hf/llava-1.5-7b-hf", "max_tokens": 128},
        "ollama_vision": {
            "model": "llava:latest",
            "max_tokens": 512,
            "probe_enabled": True,
            "probe_cache_seconds": 300,
            "image_format": "PNG",
            "keep_alive": "5m",
        },
        "llama_cpp_vision": {
            "enabled": False,
            "base_url": "http://127.0.0.1:8080",
            "model": "",
            "max_tokens": 512,
            "request_timeout": 120,
            "ping_timeout": 3.0,
            "image_format": "PNG",
        },
    }


class RAGSearchStrategySessionContext(BaseModel):
    enabled: bool = True
    max_messages: int = Field(32, alias="maxMessages")
    look_back_to_today: bool = Field(True, alias="lookBackToToday")

    class Config:
        validate_by_name = True


class RAGSearchStrategyDailySummary(BaseModel):
    enabled: bool = True
    look_back_days: int = Field(7, alias="lookBackDays")
    use_tags: bool = Field(True, alias="useTags")

    class Config:
        validate_by_name = True


class RAGSearchStrategyLongTermMemory(BaseModel):
    enabled: bool = True
    vector_search: bool = Field(True, alias="vectorSearch")
    graph_search: bool = Field(True, alias="graphSearch")
    priority_rules: bool = Field(True, alias="priorityRules")

    class Config:
        validate_by_name = True


class RAGSearchStrategyFallback(BaseModel):
    ask_user: bool = Field(True, alias="askUser")
    auto_learn: bool = Field(True, alias="autoLearn")

    class Config:
        validate_by_name = True


class RAGSearchStrategy(BaseModel):
    session_context: RAGSearchStrategySessionContext = Field(
        default_factory=RAGSearchStrategySessionContext, alias="sessionContext"
    )
    daily_summary: RAGSearchStrategyDailySummary = Field(
        default_factory=RAGSearchStrategyDailySummary, alias="dailySummary"
    )
    long_term_memory: RAGSearchStrategyLongTermMemory = Field(
        default_factory=RAGSearchStrategyLongTermMemory, alias="longTermMemory"
    )
    fallback: RAGSearchStrategyFallback = RAGSearchStrategyFallback()

    class Config:
        validate_by_name = True


class RAGMemoryFacts(BaseModel):
    enabled: bool = True
    priority_rules: List[str] = Field(
        default_factory=lambda: ["user", "name", "person"], alias="priorityRules"
    )
    auto_update: bool = Field(True, alias="autoUpdate")

    class Config:
        validate_by_name = True


class RAGMemoryGraph(BaseModel):
    enabled: bool = True
    relationships: bool = True
    inference: bool = True


class RAGMemory(BaseModel):
    facts: RAGMemoryFacts = RAGMemoryFacts()
    graph: RAGMemoryGraph = RAGMemoryGraph()


class RAGConfig(BaseModel):
    enabled: bool = True
    embedding_model: str = Field("all-MiniLM-L6-v2", alias="embeddingModel")
    vector_db_path: str = Field("./data/vector_db", alias="vectorDbPath")
    chunk_size: int = Field(500, alias="chunkSize")
    chunk_overlap: int = Field(50, alias="chunkOverlap")
    top_k: int = Field(5, alias="topK")
    similarity_threshold: float = Field(0.7, alias="similarityThreshold")
    enable_caching: bool = Field(True, alias="enableCaching")
    cache_ttl: int = Field(60, alias="cacheTtl")
    search_strategy: RAGSearchStrategy = Field(
        default_factory=RAGSearchStrategy, alias="searchStrategy"
    )
    memory: RAGMemory = RAGMemory()
    retrieval: Dict[str, Any] = Field(default_factory=dict)
    lore: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        validate_by_name = True


class AnalyzerProviderOpenRouterConfig(BaseModel):
    api_key: str = ""
    model: str = ""
    temperature: float = 0.1
    max_tokens: int = DEFAULT_MAX_TOKENS


class AnalyzerProviderOllamaConfig(BaseModel):
    model: str = "llama3.2"
    temperature: float = 0.1
    max_tokens: int = DEFAULT_MAX_TOKENS
    thinking: bool = False


class AnalyzerProviderLlamaCppConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080"
    model: str = ""
    temperature: float = 0.1
    max_tokens: int = DEFAULT_MAX_TOKENS
    request_timeout: int = 120


class AnalyzerProvidersConfig(BaseModel):
    openrouter: AnalyzerProviderOpenRouterConfig = AnalyzerProviderOpenRouterConfig()
    ollama: AnalyzerProviderOllamaConfig = AnalyzerProviderOllamaConfig()
    llama_cpp: AnalyzerProviderLlamaCppConfig = AnalyzerProviderLlamaCppConfig()


class AnalyzerConfig(BaseModel):
    enabled: bool = True
    active_provider: str = "ollama"
    fallback_order: List[str] = Field(default_factory=list)
    release_after_use: bool = True
    system_prompt: str = COGNITIVE_ANALYSIS_PROMPT
    providers: AnalyzerProvidersConfig = AnalyzerProvidersConfig()


class MoralProviderOllamaConfig(BaseModel):
    model: str = "llama3.2"
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = 512
    thinking: bool = False


class MoralProviderOpenRouterConfig(BaseModel):
    api_key: str = ""
    model: str = "openai/gpt-4o-mini"
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = 512


class MoralProviderLlamaCppConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080"
    model: str = ""
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = 512
    request_timeout: int = 120


class MoralProvidersConfig(BaseModel):
    heuristic: Dict[str, Any] = Field(default_factory=dict)
    ollama: MoralProviderOllamaConfig = MoralProviderOllamaConfig()
    openrouter: MoralProviderOpenRouterConfig = MoralProviderOpenRouterConfig()
    llama_cpp: MoralProviderLlamaCppConfig = MoralProviderLlamaCppConfig()


class MoralDecayConfig(BaseModel):
    # Nightly worker reduces EmotionalTrace.intensity by ``global_rate``
    # per day (unless a per-row rate is set). Set ``enabled=False`` to
    # freeze the emotional state — useful for testing or "max_speed"-style
    # profiles where memory must stay sharp.
    enabled: bool = True
    global_rate: float = 0.05


class MoralInnerVoiceConfig(BaseModel):
    # Single-sentence first-person explanation written by a small LLM after
    # each emotional shift. Surfaces in the existing WS moral_state event
    # via result.meta.inner_voice. Adds one short LLM call per turn —
    # disable when latency matters more than introspection UX.
    enabled: bool = True
    max_tokens: int = 80
    temperature: float = 0.7
    language: str = ""  # blank → falls back to system.language


class MoralScarTriggerConfig(BaseModel):
    """One scar trigger — see Архитектура.md > "Что не прощается"."""
    name: str = ""
    intents: List[str] = Field(default_factory=list)
    tones: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    persistence_floor: float = 0.4
    intensity_boost: float = 0.0


class MoralScarsConfig(BaseModel):
    enabled: bool = True
    triggers: List[MoralScarTriggerConfig] = Field(default_factory=list)


class MoralForgivenessConfig(BaseModel):
    # When the analyzer reports a compensating tone on the current user
    # message, the system softens recent unresolved negative traces by
    # ``delta_per_event``, clamped at each trace's ``persistence_floor``.
    enabled: bool = True
    compensating_tones: List[str] = Field(
        default_factory=lambda: [
            "warm",
            "tender",
            "kind",
            "apologetic",
            "soft",
            "loving",
        ]
    )
    softenable_emotions: List[str] = Field(
        default_factory=lambda: [
            "sadness",
            "resentment",
            "frustration",
            "anger",
            "longing",
            "fear",
            "shame",
        ]
    )
    delta_per_event: float = 0.15
    lookback_days: int = 30


class MoralMatrixConfig(BaseModel):
    enabled: bool = True
    active_provider: str = "ollama"
    fallback_order: List[str] = Field(
        default_factory=lambda: ["openrouter", "heuristic"]
    )
    release_after_use: bool = True
    system_prompt: str = MORAL_MATRIX_PROVIDER_PROMPT
    providers: MoralProvidersConfig = MoralProvidersConfig()
    decay: MoralDecayConfig = MoralDecayConfig()
    forgiveness: MoralForgivenessConfig = MoralForgivenessConfig()
    scars: MoralScarsConfig = MoralScarsConfig()
    inner_voice: MoralInnerVoiceConfig = MoralInnerVoiceConfig()


class MemoryConsolidationJudgeConfig(BaseModel):
    enabled: bool = False
    provider: str = "ollama"
    model: str = ""
    temperature: float = 0.0
    max_tokens: int = 512
    request_timeout: int = 60


class MemoryConsolidationConfig(BaseModel):
    # Diary entries whose importance_score < threshold are flagged
    # payload.pruned and hidden from default reads. 0.0 disables the filter.
    importance_threshold: float = 0.2
    judge: MemoryConsolidationJudgeConfig = MemoryConsolidationJudgeConfig()


class MemoryConfig(BaseModel):
    deep_memory_enabled: bool = True
    force_deep_memory: bool = False
    recent_limit: int = 32
    similarity_threshold: float = 0.7
    session_window: str = "day"
    session_enabled: bool = True
    embedding_provider: str = "auto"
    embedding_model: str = "nomic-embed-text"
    consolidation: MemoryConsolidationConfig = MemoryConsolidationConfig()


class SynthesisSdWebUIConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:7860"
    bearer_token: str = ""
    timeout_sec: int = 180
    checkpoint: str = ""
    sampler_name: str = "DPM++ 2M"
    scheduler: str = "Automatic"
    cfg_scale_default: float = 2.0


class SynthesisComfyUIConfig(BaseModel):
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8188"
    websocket_url: str = "ws://127.0.0.1:8188/ws"
    timeout_sec: int = 180
    default_workflow: str = ""
    default_model: str = ""
    sampler: str = "euler"
    scheduler: str = "normal"
    steps: int = 30
    cfg: float = 7.0
    width: int = 1024
    height: int = 1024
    aspect_ratio: str = "1:1"


class SynthesisDiffusersConfig(BaseModel):
    enabled: bool = True
    device: str = "auto"
    default_model: str = "z_image_turbo"
    local_models_path: str = "storage/models/image-generation"
    cache_dir: str = ""
    torch_dtype: str = "auto"
    keep_loaded: bool = True
    sampler: str = "euler"
    scheduler: str = "normal"
    steps: int = 30
    cfg: float = 7.0
    width: int = 1024
    height: int = 1024
    aspect_ratio: str = "1:1"
    allow_comfyui_fallback: bool = True


class SynthesisPromptingConfig(BaseModel):
    enabled: bool = True
    max_attempts: int = 3
    assess_enabled: bool = True
    quality_threshold: float = 0.72
    appearance_prompt: str = ""
    default_negative_prompt: str = "(text:2), (signature:2), raw photo"
    visual_profile: dict = Field(
        default_factory=lambda: {
            "character_name": "PAI",
            "appearance_textarea": "",
            "default_outfit": "",
            "default_environment": "",
            "style_preset": "anime",
            "render_profile": "default_anime",
            "selfie_bias": 0.85,
            "environment_bias": 0.10,
            "symbolic_bias": 0.05,
            "anti_repetition_strength": 0.65,
            "use_time_of_day": True,
            "use_season": True,
            "use_weather": True,
            "use_relation_state": True,
            "use_recent_topics": True,
            "selfie_composition_base": "",
            "selfie_composition_pool_override": "",
            "environment_composition_pool_override": "",
            "allow_self_images": True,
            "allow_environment_images": True,
            "allow_symbolic_images": True,
        }
    )
    per_character_visual_profiles: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    scenarios: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class SynthesisConfig(BaseModel):
    active_provider: str = "core"
    sd_webui: SynthesisSdWebUIConfig = SynthesisSdWebUIConfig()
    comfyui: SynthesisComfyUIConfig = SynthesisComfyUIConfig()
    diffusers: SynthesisDiffusersConfig = SynthesisDiffusersConfig()
    prompting: SynthesisPromptingConfig = SynthesisPromptingConfig()


class TelegramRoutingConfig(BaseModel):
    allow_private: bool = True
    allow_groups: bool = True
    allow_channels: bool = True
    write_private: bool = True
    write_groups: bool = True
    write_channels: bool = False
    read_only_non_private: bool = True
    groups_require_mention: bool = False
    allowed_chat_ids: List[int] = Field(default_factory=list)


class TelegramSyncConfig(BaseModel):
    enabled: bool = True
    startup_reindex_enabled: bool = True
    connect_reindex_enabled: bool = True
    max_chats: int = 32
    messages_per_chat: int = 80


class TelegramPersonaBindingsConfig(BaseModel):
    chat_character_map: Dict[str, str] = Field(default_factory=dict)


class TelegramLockdownConfig(BaseModel):
    enabled: bool = False
    owner_chat_id: int = 0


class TelegramPresenceConfig(BaseModel):
    enabled: bool = True
    auto_offline_after_send: bool = True


class TelegramChannelsConfig(BaseModel):
    read_enabled: bool = True
    mark_read_enabled: bool = True
    reflect_enabled: bool = False
    reflection_instruction: str = (
        "Reflect shortly on key facts and implications from this channel post."
    )


class TelegramWritePolicyConfig(BaseModel):
    allow_private: bool = True
    allow_groups: bool = False
    allow_channels: bool = False
    allowed_private_chat_ids: List[int] = Field(default_factory=list)
    denied_chat_ids: List[int] = Field(default_factory=list)
    sandbox_chat_ids: List[int] = Field(default_factory=list)


class TelegramReflectionConfig(BaseModel):
    enabled: bool = True
    source_chat_ids: List[int] = Field(default_factory=list)
    source_chat_kinds: List[str] = Field(default_factory=lambda: ["channel", "group"])
    target_chat_id: int = 0
    prompt: str = (
        "Read the public Telegram post below and write a short private reflection for the owner. "
        "Do not address the public chat. Do not write as a reply to the channel. "
        "Summarize what happened, what the PAI thinks about it, and why it may matter."
    )
    include_source_excerpt: bool = True
    include_source_link: bool = True
    max_source_excerpt_chars: int = 800
    max_reflection_length: int = 1200
    min_source_text_chars: int = 25
    cooldown_per_source_chat_seconds: int = 90
    dedup_enabled: bool = True


class TelegramQuietHoursConfig(BaseModel):
    enabled: bool = True
    start: str = "00:00"
    end: str = "09:00"


class TelegramAntiSpamConfig(BaseModel):
    per_chat_max_messages: int = 5
    global_max_messages: int = 24
    window_seconds: float = 15.0
    min_delay_seconds: float = 0.7
    typing_delay_enabled: bool = True
    typing_ms_per_char: float = 22.0
    typing_min_ms: float = 220.0
    typing_max_ms: float = 2200.0


class TelegramAntiRepeatConfig(BaseModel):
    history_size: int = 32
    similarity_threshold: float = 0.92
    jaccard_threshold: float = 0.88
    semantic_enabled: bool = True
    semantic_history_size: int = 32
    semantic_max_similarity_threshold: float = 0.75
    semantic_avg_similarity_threshold: float = 0.73
    semantic_provider: str = "auto"
    semantic_model: str = "nomic-embed-text"
    enforce_for_incoming_dialogs: bool = False
    retry_on_block: bool = True
    retry_attempts: int = 1
    retry_use_memory: bool = True
    retry_memory_chars: int = 1200


class TelegramInitiativeConfig(BaseModel):
    enabled: bool = False
    check_every_seconds: int = 60
    idle_minutes: int = 60
    min_gap_minutes: int = 30
    max_proactive_per_day: int = 3
    morning_checkin_enabled: bool = True
    evening_checkin_enabled: bool = True
    daily_digest_enabled: bool = True
    daily_digest_window_start: str = "20:00"
    daily_digest_window_end: str = "22:00"
    owner_chat_only: bool = True
    bootstrap_from_catalog: bool = True
    bootstrap_max_chats: int = 64
    allow_private: bool = True
    allow_groups: bool = False
    prompt_template: str = (
        "You have not heard from this chat for {idle_minutes} minutes. "
        "Send one short warm proactive message, if appropriate."
    )


class TelegramAutonomousInboxConfig(BaseModel):
    enabled: bool = False
    check_every_seconds: int = 45
    max_candidates: int = 8
    max_actions_per_cycle: int = 2
    include_private: bool = True
    include_groups: bool = True
    include_channels: bool = True
    private_pause_probability: float = 0.2
    prompt_template: str = (
        "You are online and received unread events in Telegram. "
        "Choose one action: open chat, answer, read channel, or pause."
    )


class TelegramToolSwitchesConfig(BaseModel):
    get_telegram_chats: bool = True
    open_chat_by_id: bool = True
    get_chat_photo: bool = True
    ask_memory: bool = True
    take_photo: bool = True
    send_generated_photo: bool = True
    send_telegram_message: bool = True
    ask_google: bool = True
    wait_pause: bool = True


class TelegramOrchestrationConfig(BaseModel):
    enabled: bool = True
    allow_llm_tool_actions: bool = False
    max_rounds: int = 4
    max_tool_output_chars: int = 3000
    max_manual_sends_per_turn: int = 3
    require_tool_call: bool = False
    max_no_tool_retries: int = 2
    tools: TelegramToolSwitchesConfig = TelegramToolSwitchesConfig()


class TelegramImageConfig(BaseModel):
    enabled: bool = True
    command_prefix: str = "/image"
    default_model: str = ""
    negative_prompt: str = ""
    width: int = 1024
    height: int = 1024
    num_inference_steps: int = 9
    guidance_scale: float = 0.0
    caption_template: str = "Generated image ✨"
    autonomous_random_enabled: bool = False
    autonomous_random_probability: float = 0.5


class TelegramMediaConfig(BaseModel):
    ingest_enabled: bool = True
    max_incoming_media_bytes: int = 2_000_000


class TelegramFormattingConfig(BaseModel):
    max_chars_per_message: int = 700
    max_messages_per_turn: int = 3


class TelegramConfig(BaseModel):
    enabled: bool = False
    mode: str = "mtproto"
    api_id: int = 0
    api_hash: str = ""
    session_name: str = "z_waif"
    session_dir: str = "data/telegram"
    phone_number: str = ""
    bot_token: str = ""
    queue_size: int = 256
    history_max_messages: int = 24
    sync: TelegramSyncConfig = TelegramSyncConfig()
    persona_bindings: TelegramPersonaBindingsConfig = TelegramPersonaBindingsConfig()
    lockdown: TelegramLockdownConfig = TelegramLockdownConfig()
    presence: TelegramPresenceConfig = TelegramPresenceConfig()
    routing: TelegramRoutingConfig = TelegramRoutingConfig()
    write_policy: TelegramWritePolicyConfig = TelegramWritePolicyConfig()
    channels: TelegramChannelsConfig = TelegramChannelsConfig()
    reflection: TelegramReflectionConfig = TelegramReflectionConfig()
    quiet_hours: TelegramQuietHoursConfig = TelegramQuietHoursConfig()
    anti_spam: TelegramAntiSpamConfig = TelegramAntiSpamConfig()
    anti_repeat: TelegramAntiRepeatConfig = TelegramAntiRepeatConfig()
    initiative: TelegramInitiativeConfig = TelegramInitiativeConfig()
    autonomous_inbox: TelegramAutonomousInboxConfig = TelegramAutonomousInboxConfig()
    orchestration: TelegramOrchestrationConfig = TelegramOrchestrationConfig()
    image: TelegramImageConfig = TelegramImageConfig()
    media: TelegramMediaConfig = TelegramMediaConfig()
    formatting: TelegramFormattingConfig = TelegramFormattingConfig()


class GeneratorProviderBaseConfig(BaseModel):
    model: str = "llama3.2"
    temperature: float = DEFAULT_TEMPERATURE
    max_tokens: int = DEFAULT_MAX_TOKENS


class GeneratorProviderOllamaConfig(GeneratorProviderBaseConfig):
    streaming: bool = True
    base_url: str = "http://localhost:11434"


class GeneratorProviderOpenRouterConfig(GeneratorProviderBaseConfig):
    api_key: str = ""
    base_url: str = OPENROUTER_BASE_URL


class GeneratorProviderTransformersConfig(GeneratorProviderBaseConfig):
    model: str = ""
    streaming: bool = True
    device_map: str = "auto"
    torch_dtype: str = "auto"
    trust_remote_code: bool = True
    low_cpu_mem_usage: bool = True
    do_sample: bool = True
    top_p: float = 0.9
    top_k: int = 50
    repetition_penalty: float = 1.1
    keep_loaded: bool = True
    source: str = "huggingface"


class GeneratorProviderLlamaCppConfig(GeneratorProviderBaseConfig):
    # Off by default — the user must explicitly point at a llama-server before
    # the manager will route to this provider.
    enabled: bool = False
    base_url: str = "http://127.0.0.1:8080"
    streaming: bool = True
    request_timeout: int = 300
    stream_timeout: int = 600
    # Extra samplers exposed by llama-server's OpenAI endpoint. ``temperature``
    # and ``max_tokens`` come from the base class.
    top_p: float = 0.9
    top_k: int = 50
    min_p: float = 0.05
    repeat_penalty: float = 1.1


class APIProvidersConfig(BaseModel):
    ollama: GeneratorProviderOllamaConfig = GeneratorProviderOllamaConfig()
    openrouter: GeneratorProviderOpenRouterConfig = GeneratorProviderOpenRouterConfig()
    transformers: GeneratorProviderTransformersConfig = GeneratorProviderTransformersConfig()
    llama_cpp: GeneratorProviderLlamaCppConfig = GeneratorProviderLlamaCppConfig()


class APIConfig(BaseModel):
    type: str = "Ollama"
    streaming: bool = True
    model: str = "llama3.2"
    visual_model: str = "apple/FastVLM-1.5B"
    visual_model_options: List[str] = Field(default_factory=lambda: ["apple/FastVLM-1.5B"])
    token_limit: int = 4096
    message_pair_limit: int = 4
    active_provider: str = "ollama"
    fallback_order: List[str] = Field(default_factory=list)
    providers: APIProvidersConfig = APIProvidersConfig()


class GenerateSettingsConfig(BaseModel):
    temperature: float = 0.85
    min_p: float = 0.05
    top_p: float = 0.9
    top_k: int = 50
    repeat_penalty: float = 1.2
    stop: Optional[Any] = None
    num_predict: int = 2048
    normalize_messages: bool = False
    name: str = "Default"
    description: str = "Basic generation parameters"


# ---------------------------
# AppConfig
# ---------------------------
class AppConfig(BaseModel):
    system: SystemConfig = SystemConfig()
    core: CoreConfig = CoreConfig()
    decision_layer: DecisionLayerConfig = DecisionLayerConfig()
    connector: ConnectorConfig = ConnectorConfig()
    voice: "VoiceConfig" = None
    stt: "STTConfig" = None
    modules: "ModulesConfig" = None
    communication: "CommunicationConfig" = None
    audio: "AudioConfig" = None
    vision: "VisionConfig" = None
    rag: "RAGConfig" = None
    analyzer: "AnalyzerConfig" = None
    moral: "MoralMatrixConfig" = None
    memory: "MemoryConfig" = None
    synthesis: "SynthesisConfig" = None
    telegram: "TelegramConfig" = None
    api: "APIConfig" = None
    generate_settings: "GenerateSettingsConfig" = None

    class Config:
        arbitrary_types_allowed = True


# Configuration paths for easy access
CONFIG_PATHS = {
    "config": "config/config.json",
    "presets": "config/generation_presets.json",
}
