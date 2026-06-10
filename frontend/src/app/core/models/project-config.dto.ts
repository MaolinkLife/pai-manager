export interface BaseConfigDto {
    user_id?: string;
    char_name?: string;
    user_name?: string;
    language?: string;
}

export interface VoiceModuleConfigDto {
    [key: string]: any;
}

export interface VoiceConfigDto {
    enabled: boolean;
    output_id: number;
    windows_output_id: number;
    language: string;
    use_rvc: boolean;
    voice_language: string;
    use_windows_output: boolean;
    streaming_tts: boolean;
    enable_fallback: boolean;
    active_module: string;
    rvc?: {
        enabled?: boolean;
        model_file?: string;
        pitch?: number;
        filter_radius?: number;
        rms_mix_rate?: number;
        protect?: number;
        f0_method?: string;
        split_audio?: boolean;
        autotune?: boolean;
        embedder_model?: string;
    };
    voice_modules: VoiceModuleConfigDto;
}

export interface ModuleConfigDto {
    vtube_studio: boolean;
    whisper: boolean;
    minecraft: boolean;
    gaming: boolean;
    alarm: boolean;
    discord: boolean;
    telegram?: boolean;
    rag: boolean;
    visual: boolean;
}

export interface DecisionLayerConfigDto {
    mode: 'system' | 'llm';
    active_provider: string;
    max_steps: number;
    release_after_use?: boolean;
    capabilities: {
        tool: boolean;
        vision: boolean;
        thinking: boolean;
    };
    providers: {
        ollama: {
            model: string;
            temperature: number;
            max_tokens: number;
            thinking?: boolean;
        };
        [key: string]: any;
    };
    instructor?: {
        build_schema?: string;
        include_datetime?: boolean;
        include_geolocation?: boolean;
        exclude_disabled_modules?: boolean;
    };
}

export interface TunnelingConfigDto {
    enabled: boolean;
    provider: string;
    local_url: string;
    local_port: number;
    command_path: string;
    public_url: string;
}

export interface ConnectorConfigDto {
    tunneling: TunnelingConfigDto;
}

export interface AudioConfigDto {
    input_device_id?: number;
    sample_rate?: number;
    channels?: number;
    chunk_size?: number;
    enable_vad?: boolean;
    vad_threshold?: number;
    silence_timeout?: number;
    min_audio_length?: number;
    max_audio_length?: number;
    trigger_words?: string[];
    ignore_trigger_words?: boolean;
}

export interface VisionModuleConfigDto {
    [key: string]: any;
}

export interface VisionConfigDto {
    enabled: boolean;
    active_provider?: string;
    monitor_index: number;
    fps: number;
    buffer_sec: number;
    downscale_width: number;
    yolo_enabled: boolean;
    ocr_lang: string;
    ocr_min_conf: number;
    ocr_max_lines: number;
    region: any;
    capture_mode?: string;
    window_title?: string;
    window_process?: string;
    debug_save?: boolean;
    debug_path?: string;
    vision_modules: VisionModuleConfigDto;
}

export interface RagVectorProfileDto {
    label?: string;
    enabled?: boolean;
    provider?: string;
    model?: string;
    top_k?: number;
    threshold?: number;
    endpoint?: string;
    timeout?: number;
    max_retries?: number;
    retry_backoff?: number;
    device?: string;
}

export interface RagRetrievalDto {
    recent?: { limit?: number };
    session?: {
        enabled?: boolean;
        window?: string;
        idle_gap_minutes?: number;
        max_messages?: number;
        chunk_size?: number;
    };
    keyword?: {
        enabled?: boolean;
        max_candidates?: number;
        min_score?: number;
        min_overlap?: number;
        boost_user?: number;
        boost_assistant?: number;
        stopwords?: string[];
    };
    vectors?: {
        primary?: string;
        profiles?: Record<string, RagVectorProfileDto>;
    };
    short_term?: { enabled?: boolean; threshold?: number; lookback_days?: number };
    emotional?: { enabled?: boolean; lookback_days?: number; limit?: number };
    rerank?: {
        enabled?: boolean;
        top_n?: number;
        use_primary_rerank?: boolean;
        boost_recency?: number;
        weights?: {
            embedding?: number;
            keyword?: number;
            short_term?: number;
        };
    };
}

export interface RagLoreDto {
    top_k?: number;
    similarity_threshold?: number;
}

export interface RagConfigDto {
    enabled: boolean;
    embedding_model?: string;
    vector_db_path?: string;
    chunk_size?: number;
    chunk_overlap?: number;
    top_k?: number;
    similarity_threshold?: number;
    enable_caching?: boolean;
    cache_ttl?: number;
    search_strategy?: any;
    memory?: any;
    retrieval?: RagRetrievalDto;
    lore?: RagLoreDto;
}

export interface AnalyzerProviderConfigDto {
    api_key?: string;
    model?: string;
    temperature?: number;
    max_tokens?: number;
    enabled?: boolean;
    base_url?: string;
    request_timeout?: number;
}

export interface AnalyzerConfigDto {
    enabled?: boolean;
    active_provider: string;
    fallback_order: string[];
    release_after_use?: boolean;
    system_prompt?: string;
    providers: {
        [key: string]: AnalyzerProviderConfigDto;
    };
}

export interface MoralProviderConfigDto {
    api_key?: string;
    model?: string;
    temperature?: number;
    max_tokens?: number;
    thinking?: boolean;
    enabled?: boolean;
    base_url?: string;
    request_timeout?: number;
}

export interface MoralDecayConfigDto {
    enabled?: boolean;
    global_rate?: number;
}

export interface MoralForgivenessConfigDto {
    enabled?: boolean;
    compensating_tones?: string[];
    softenable_emotions?: string[];
    delta_per_event?: number;
    lookback_days?: number;
}

export interface MoralScarTriggerDto {
    name?: string;
    intents?: string[];
    tones?: string[];
    keywords?: string[];
    persistence_floor?: number;
    intensity_boost?: number;
}

export interface MoralScarsConfigDto {
    enabled?: boolean;
    triggers?: MoralScarTriggerDto[];
}

export interface MoralInnerVoiceConfigDto {
    enabled?: boolean;
    max_tokens?: number;
    temperature?: number;
    language?: string;
}

export interface MoralConfigDto {
    enabled: boolean;
    active_provider: string;
    fallback_order: string[];
    release_after_use?: boolean;
    system_prompt?: string;
    providers: {
        heuristic?: Record<string, any>;
        ollama?: MoralProviderConfigDto;
        openrouter?: MoralProviderConfigDto;
        llama_cpp?: MoralProviderConfigDto;
    };
    decay?: MoralDecayConfigDto;
    forgiveness?: MoralForgivenessConfigDto;
    scars?: MoralScarsConfigDto;
    inner_voice?: MoralInnerVoiceConfigDto;
}

export interface MemoryDiaryNarrativeConfigDto {
    enabled?: boolean;
    min_chars?: number;
    max_chars?: number;
}

export interface MemoryDiaryConfigDto {
    narrative?: MemoryDiaryNarrativeConfigDto;
}

export interface MemoryConsolidationJudgeDto {
    enabled?: boolean;
    provider?: string;
    model?: string;
    temperature?: number;
    max_tokens?: number;
    request_timeout?: number;
}

export interface MemoryConsolidationConfigDto {
    importance_threshold?: number;
    judge?: MemoryConsolidationJudgeDto;
}

export interface MemoryConfigDto {
    deep_memory_enabled?: boolean;
    recent_limit: number;
    similarity_threshold: number;
    session_window: string;
    session_enabled: boolean;
    embedding_provider: string;
    embedding_model: string;
    consolidation?: MemoryConsolidationConfigDto;
    diary?: MemoryDiaryConfigDto;
}

// --- STT (0.7.2 — whisper + sherpa-onnx) -----------------------------------

export interface SttSherpaOnnxConfigDto {
    model_type?: string;
    encoder?: string;
    decoder?: string;
    joiner?: string;
    paraformer?: string;
    whisper_encoder?: string;
    whisper_decoder?: string;
    moonshine_preprocessor?: string;
    moonshine_encoder?: string;
    moonshine_uncached_decoder?: string;
    moonshine_cached_decoder?: string;
    tokens?: string;
    num_threads?: number;
    provider?: string;
}

export interface SttConfigDto {
    language?: string;
    auto_detect?: boolean;
    provider?: string;
    sherpa_onnx?: SttSherpaOnnxConfigDto;
}

// --- Compliance pipeline (0.9.0) -------------------------------------------

export interface ValidatorConfigDto {
    enabled?: boolean;
    threshold?: number;
    max_tokens?: number;
    temperature?: number;
    instruction_char_limit?: number;
    output_char_limit?: number;
}

export interface LanguageGuardConfigDto {
    enabled?: boolean;
    min_dominance?: number;
    min_output_chars?: number;
}

export interface ConfidenceConfigDto {
    enabled?: boolean;
    threshold?: number;
    max_tokens?: number;
    temperature?: number;
    user_char_limit?: number;
    output_char_limit?: number;
}

export interface FactualityConfigDto {
    enabled?: boolean;
    gate_on_low_confidence?: boolean;
    top_k?: number;
    min_similarity?: number;
    max_claims?: number;
    claim_min_length?: number;
}

export interface SelfWatcherConfigDto {
    enabled?: boolean;
    mismatch_threshold?: number;
    nightly_reflection_enabled?: boolean;
    lookback_days?: number;
    max_events_in_cluster?: number;
    llm_max_tokens?: number;
    llm_temperature?: number;
}

// --- Audit logs retention (0.9.0 §3.6-bis) ---------------------------------

export interface AuditLogsRetentionConfigDto {
    enabled?: boolean;
    age_days?: Record<string, number>;
    hard_cap?: Record<string, number>;
}

export interface AuditLogsConfigDto {
    retention?: AuditLogsRetentionConfigDto;
}

export interface SynthesisSdWebUIConfigDto {
    enabled: boolean;
    base_url: string;
    bearer_token: string;
    timeout_sec: number;
    checkpoint: string;
    sampler_name: string;
    scheduler: string;
    cfg_scale_default: number;
}

export interface SynthesisComfyUIConfigDto {
    enabled: boolean;
    base_url: string;
    websocket_url: string;
    timeout_sec: number;
    default_workflow: string;
    default_model: string;
    sampler?: string;
    scheduler?: string;
    steps?: number;
    cfg?: number;
    width?: number;
    height?: number;
    aspect_ratio?: string;
}

export interface SynthesisDiffusersConfigDto {
    enabled: boolean;
    device: string;
    default_model: string;
    local_models_path: string;
    cache_dir: string;
    torch_dtype: string;
}

export interface SynthesisPromptingConfigDto {
    enabled: boolean;
    max_attempts: number;
    assess_enabled: boolean;
    retry_enabled?: boolean;
    quality_threshold: number;
    appearance_prompt: string;
    default_negative_prompt: string;
    visual_profile?: {
        character_name?: string;
        appearance_textarea?: string;
        default_outfit?: string;
        default_environment?: string;
        style_preset?: string;
        render_profile?: string;
        selfie_bias?: number;
        environment_bias?: number;
        symbolic_bias?: number;
        anti_repetition_strength?: number;
        use_time_of_day?: boolean;
        use_season?: boolean;
        use_weather?: boolean;
        use_relation_state?: boolean;
        use_recent_topics?: boolean;
        selfie_composition_base?: string;
        selfie_composition_pool_override?: string;
        environment_composition_pool_override?: string;
        allow_self_images?: boolean;
        allow_environment_images?: boolean;
        allow_symbolic_images?: boolean;
    };
    per_character_visual_profiles?: Record<string, SynthesisPromptingConfigDto['visual_profile']>;
    scenarios?: Record<string, {
        title?: string;
        enabled?: boolean;
        image_provider?: string;
        image_model?: string;
        width?: number | null;
        height?: number | null;
        steps?: number | null;
        num_inference_steps?: number | null;
        cfg?: number | null;
        guidance_scale?: number | null;
        sampler?: string;
        scheduler?: string;
        use_prompt_builder?: boolean;
        review_generated_image?: boolean;
        use_visual_intent?: boolean;
        prompt_policy?: string;
        style_prompt?: string;
        negative_prompt?: string;
        system_prompt?: string;
    }>;
}

export interface SynthesisConfigDto {
    active_provider?: string;
    sd_webui: SynthesisSdWebUIConfigDto;
    comfyui: SynthesisComfyUIConfigDto;
    diffusers: SynthesisDiffusersConfigDto;
    prompting?: SynthesisPromptingConfigDto;
}

export interface GeneratorProviderConfigDto {
    model: string;
    temperature?: number;
    max_tokens?: number;
    streaming?: boolean;
    api_key?: string;
    base_url?: string;
    [key: string]: any;
}

export interface ApiConfigDto {
    type: string;
    streaming: boolean;
    model: string;
    visual_model: string;
    visual_model_options?: string[];
    token_limit: number;
    message_pair_limit: number;
    active_provider: string;
    fallback_order: string[];
    providers: {
        [key: string]: GeneratorProviderConfigDto;
    };
}

export interface GenerationConfigDto {
    temperature: number;
    min_p: number;
    top_p: number;
    top_k: number;
    repeat_penalty: number;
    stop: string[] | null;
    num_predict: number;
    name?: string;
    description?: string;
}

export interface SystemConfigDto {
    user_id?: string;
    user_name?: string;
    char_name?: string;
    system_prompt?: string;
    language?: string;
    theme?: string;
    runtime?: {
        model_memory_profile?: string;
    };
}

export interface ProjectConfigDto extends BaseConfigDto {
    voice: VoiceConfigDto;
    modules: ModuleConfigDto;
    decision_layer: DecisionLayerConfigDto;
    connector: ConnectorConfigDto;
    telegram?: any;
    communication?: any;
    synthesis?: SynthesisConfigDto;
    audio: AudioConfigDto;
    vision: VisionConfigDto;
    rag: RagConfigDto;
    analyzer: AnalyzerConfigDto;
    moral: MoralConfigDto;
    memory: MemoryConfigDto;
    api: ApiConfigDto;
    generate_settings: GenerationConfigDto;
    system: SystemConfigDto;
    // 0.9.0 — compliance pipeline + audit logs retention
    validator?: ValidatorConfigDto;
    language_guard?: LanguageGuardConfigDto;
    confidence?: ConfidenceConfigDto;
    factuality?: FactualityConfigDto;
    self_watcher?: SelfWatcherConfigDto;
    audit_logs?: AuditLogsConfigDto;
    stt?: SttConfigDto;
}
