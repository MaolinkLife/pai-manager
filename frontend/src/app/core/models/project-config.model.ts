export interface ProjectConfig {
    voice: VoiceConfig;
    modules: ModuleConfig;
    decisionLayer: DecisionLayerConfig;
    connector: ConnectorConfig;
    telegram?: any;
    communication?: any;
    synthesis?: SynthesisConfig;
    vision: VisionConfig;
    audio: AudioConfig;
    rag: RagConfig;
    api: ApiConfig;
    analyzer: AnalyzerConfig;
    moral: MoralConfig;
    memory: MemoryConfig;
    generateSettings: GenerationConfig;
    system: SystemConfig;
    // 0.9.0 — compliance pipeline + audit logs retention
    validator?: ValidatorConfig;
    languageGuard?: LanguageGuardConfig;
    confidence?: ConfidenceConfig;
    factuality?: FactualityConfig;
    selfWatcher?: SelfWatcherConfig;
    auditLogs?: AuditLogsConfig;
    stt?: SttConfig;
}

export interface DecisionLayerConfig {
    mode: 'system' | 'llm';
    activeProvider: string;
    maxSteps: number;
    releaseAfterUse?: boolean;
    capabilities: {
        tool: boolean;
        vision: boolean;
        thinking: boolean;
    };
    providers: {
        ollama: {
            model: string;
            temperature: number;
            maxTokens: number;
            thinking?: boolean;
        };
        [key: string]: any;
    };
    instructor?: {
        buildSchema: string;
        includeDatetime: boolean;
        includeGeolocation: boolean;
        excludeDisabledModules: boolean;
    };
}

export interface TunnelingConfig {
    enabled: boolean;
    provider: string;
    localUrl: string;
    localPort: number;
    commandPath: string;
    publicUrl: string;
}

export interface ConnectorConfig {
    tunneling: TunnelingConfig;
}

export interface VoiceConfig {
    enabled: boolean;
    outputId: number;
    windowsOutputId: number;
    language: string;
    useRvc: boolean;
    voiceLanguage: string;
    useWindowsOutput: boolean;
    streamingTts: boolean;
    enableFallback: boolean;
    activeModule: string;
    rvc?: {
        enabled?: boolean;
        modelFile?: string;
        pitch?: number;
        filterRadius?: number;
        rmsMixRate?: number;
        protect?: number;
        f0Method?: string;
        splitAudio?: boolean;
        autotune?: boolean;
        embedderModel?: string;
    };
    voiceModules: Record<string, any>
}

export interface ModuleConfig {
    vtubeStudio: boolean;
    whisper: boolean;
    minecraft: boolean;
    gaming: boolean;
    alarm: boolean;
    discord: boolean;
    telegram?: boolean;
    rag: boolean;
    visual: boolean;
}

export type VisionModuleConfig = Record<string, any>;

export interface SystemConfig {
    userId: string;
    charName: string;
    userName: string;
    systemPrompt: string;
    language: string;
    theme: string;
    runtime?: {
        modelMemoryProfile?: string;
    };
}

export interface VisionConfig {
    enabled: boolean;
    activeProvider: string;
    monitorIndex: number;
    fps: number;
    bufferSec: number;
    downscaleWidth: number;
    yoloEnabled: boolean;
    ocrLang: string;
    ocrMinConf: number;
    ocrMaxLines: number;
    region: any;
    captureMode: string;
    windowTitle: string;
    windowProcess: string;
    debugSave: boolean;
    debugPath: string;
    visionModules: Record<string, VisionModuleConfig>;
}

export interface AnalyzerProviderConfig {
    apiKey?: string;
    model?: string;
    temperature?: number;
    maxTokens?: number;
    enabled?: boolean;
    baseUrl?: string;
    requestTimeout?: number;
}

export interface AnalyzerConfig {
    enabled?: boolean;
    activeProvider: string;
    fallbackOrder: string[];
    releaseAfterUse?: boolean;
    systemPrompt?: string;
    providers: {
        [key: string]: AnalyzerProviderConfig;
    };
}

export interface MoralProviderConfig {
    model?: string;
    temperature?: number;
    maxTokens?: number;
    apiKey?: string;
    thinking?: boolean;
    enabled?: boolean;
    baseUrl?: string;
    requestTimeout?: number;
}

export interface MoralProvidersConfig {
    heuristic?: Record<string, any>;
    ollama?: MoralProviderConfig;
    openrouter?: MoralProviderConfig;
    llamaCpp?: MoralProviderConfig;
}

export interface MoralDecayConfig {
    enabled: boolean;
    globalRate: number;
}

export interface MoralForgivenessConfig {
    enabled: boolean;
    compensatingTones: string[];
    softenableEmotions: string[];
    deltaPerEvent: number;
    lookbackDays: number;
}

export interface MoralScarTrigger {
    name: string;
    intents: string[];
    tones: string[];
    keywords: string[];
    persistenceFloor: number;
    intensityBoost: number;
}

export interface MoralScarsConfig {
    enabled: boolean;
    triggers: MoralScarTrigger[];
}

export interface MoralInnerVoiceConfig {
    enabled: boolean;
    maxTokens: number;
    temperature: number;
    language: string;
}

export interface MoralConfig {
    enabled: boolean;
    activeProvider: string;
    fallbackOrder: string[];
    releaseAfterUse?: boolean;
    systemPrompt?: string;
    providers: MoralProvidersConfig;
    decay?: MoralDecayConfig;
    forgiveness?: MoralForgivenessConfig;
    scars?: MoralScarsConfig;
    innerVoice?: MoralInnerVoiceConfig;
}

export interface MemoryDiaryNarrativeConfig {
    enabled: boolean;
    minChars: number;
    maxChars: number;
}

export interface MemoryDiaryConfig {
    narrative: MemoryDiaryNarrativeConfig;
}

export interface MemoryConsolidationJudgeConfig {
    enabled: boolean;
    provider: string;
    model: string;
    temperature: number;
    maxTokens: number;
    requestTimeout: number;
}

export interface MemoryConsolidationConfig {
    importanceThreshold: number;
    judge: MemoryConsolidationJudgeConfig;
}

export interface MemoryConfig {
    deepMemoryEnabled?: boolean;
    recentLimit: number;
    similarityThreshold: number;
    sessionWindow: string;
    sessionEnabled: boolean;
    embeddingProvider: string;
    embeddingModel: string;
    consolidation?: MemoryConsolidationConfig;
    diary?: MemoryDiaryConfig;
}

// --- STT (0.7.2) -----------------------------------------------------------

export interface SttSherpaOnnxConfig {
    modelType: string;
    encoder: string;
    decoder: string;
    joiner: string;
    paraformer: string;
    whisperEncoder: string;
    whisperDecoder: string;
    moonshinePreprocessor: string;
    moonshineEncoder: string;
    moonshineUncachedDecoder: string;
    moonshineCachedDecoder: string;
    tokens: string;
    numThreads: number;
    provider: string;
}

export interface SttConfig {
    language: string;
    autoDetect: boolean;
    provider: string;
    sherpaOnnx: SttSherpaOnnxConfig;
}

// --- Compliance pipeline (0.9.0) -------------------------------------------

export interface ValidatorConfig {
    enabled: boolean;
    threshold: number;
    maxTokens: number;
    temperature: number;
    instructionCharLimit: number;
    outputCharLimit: number;
}

export interface LanguageGuardConfig {
    enabled: boolean;
    minDominance: number;
    minOutputChars: number;
}

export interface ConfidenceConfig {
    enabled: boolean;
    threshold: number;
    maxTokens: number;
    temperature: number;
    userCharLimit: number;
    outputCharLimit: number;
}

export interface FactualityConfig {
    enabled: boolean;
    gateOnLowConfidence: boolean;
    topK: number;
    minSimilarity: number;
    maxClaims: number;
    claimMinLength: number;
}

export interface SelfWatcherConfig {
    enabled: boolean;
    mismatchThreshold: number;
    nightlyReflectionEnabled: boolean;
    lookbackDays: number;
    maxEventsInCluster: number;
    llmMaxTokens: number;
    llmTemperature: number;
}

// --- Audit logs retention (0.9.0 §3.6-bis) ---------------------------------

export interface AuditLogsRetentionConfig {
    enabled: boolean;
    ageDays: Record<string, number>;
    hardCap: Record<string, number>;
}

export interface AuditLogsConfig {
    retention: AuditLogsRetentionConfig;
}

export interface SynthesisSdWebUIConfig {
    enabled: boolean;
    base_url: string;
    bearer_token: string;
    timeout_sec: number;
    checkpoint: string;
    sampler_name: string;
    scheduler: string;
    cfg_scale_default: number;
}

export interface SynthesisComfyUIConfig {
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

export interface SynthesisDiffusersConfig {
    enabled: boolean;
    device: string;
    default_model: string;
    local_models_path: string;
    cache_dir: string;
    torch_dtype: string;
}

export interface SynthesisPromptingConfig {
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
    per_character_visual_profiles?: Record<string, SynthesisPromptingConfig['visual_profile']>;
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

export interface SynthesisConfig {
    active_provider?: string;
    sd_webui: SynthesisSdWebUIConfig;
    comfyui: SynthesisComfyUIConfig;
    diffusers: SynthesisDiffusersConfig;
    prompting?: SynthesisPromptingConfig;
}

export interface AudioConfig {
    inputDeviceId?: number;
    sampleRate?: number;
    channels?: number;
    chunkSize?: number;
    enableVad?: boolean;
    vadThreshold?: number;
    silenceTimeout?: number;
    minAudioLength?: number;
    maxAudioLength?: number;
    triggerWords?: string[];
    ignoreTriggerWords?: boolean;
}

export interface RagKeywordConfig {
    enabled: boolean;
    maxCandidates: number;
    minScore: number;
    minOverlap: number;
    boostUser: number;
    boostAssistant: number;
    stopwords: string[];
}

export interface RagVectorProfile {
    label?: string;
    enabled: boolean;
    provider: string;
    model: string;
    topK: number;
    threshold: number;
    endpoint?: string;
    timeout?: number;
    maxRetries?: number;
    retryBackoff?: number;
    device?: string;
}

export interface RagVectorsConfig {
    primary: string;
    profiles: Record<string, RagVectorProfile>;
}

export interface RagShortTermConfig {
    enabled: boolean;
    threshold: number;
    lookbackDays: number;
}

export interface RagEmotionalConfig {
    enabled: boolean;
    lookbackDays: number;
    limit: number;
}

export interface RagRerankWeights {
    embedding: number;
    keyword: number;
    shortTerm: number;
}

export interface RagRerankConfig {
    enabled: boolean;
    topN: number;
    usePrimaryRerank: boolean;
    boostRecency: number;
    weights: RagRerankWeights;
}

export interface RagRetrievalConfig {
    recent: { limit: number };
    session: {
        enabled: boolean;
        window: string;
        idleGapMinutes: number;
        maxMessages: number;
        chunkSize: number;
    };
    keyword: RagKeywordConfig;
    vectors: RagVectorsConfig;
    shortTerm: RagShortTermConfig;
    emotional?: RagEmotionalConfig;
    rerank: RagRerankConfig;
}

export interface RagLoreConfig {
    topK: number;
    similarityThreshold: number;
}

export interface RagConfig {
    enabled: boolean;
    embeddingModel?: string;
    vectorDbPath?: string;
    chunkSize?: number;
    chunkOverlap?: number;
    topK?: number;
    similarityThreshold?: number;
    enableCaching?: boolean;
    cacheTtl?: number;
    retrieval?: RagRetrievalConfig;
    lore?: RagLoreConfig;
    searchStrategy?: any;
    memory?: any;
}

export interface ApiConfig {
    type: string;
    streaming: boolean;
    model: string;
    visualModel: string;
    visualModelOptions?: string[];
    tokenLimit: number;
    messagePairLimit: number;
    activeProvider: string;
    fallbackOrder: string[];
    providers: Record<string, GeneratorProviderConfig>;
}

export interface GenerationConfig {
    temperature: number;
    minP: number;
    topP: number;
    topK: number;
    repeatPenalty: number;
    stop: string[] | null;
    numPredict: number;
    normalizeMessages: boolean;
    name?: string;
    description?: string;
}

export interface GeneratorProviderConfig {
    model: string;
    temperature: number;
    maxTokens: number;
    streaming?: boolean;
    apiKey?: string;
    baseUrl?: string;
    [key: string]: any;
}
