export interface ProjectConfig {
    voice: VoiceConfig;
    modules: ModuleConfig;
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
}

export interface AnalyzerConfig {
    activeProvider: string;
    fallbackOrder: string[];
    providers: {
        [key: string]: AnalyzerProviderConfig;
    };
}

export interface MoralProviderConfig {
    model?: string;
    temperature?: number;
    maxTokens?: number;
    apiKey?: string;
}

export interface MoralProvidersConfig {
    heuristic?: Record<string, any>;
    ollama?: MoralProviderConfig;
    openrouter?: MoralProviderConfig;
}

export interface MoralConfig {
    enabled: boolean;
    activeProvider: string;
    fallbackOrder: string[];
    providers: MoralProvidersConfig;
}

export interface MemoryConfig {
    deepMemoryEnabled?: boolean;
    recentLimit: number;
    similarityThreshold: number;
    sessionWindow: string;
    sessionEnabled: boolean;
    embeddingProvider: string;
    embeddingModel: string;
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
}

export interface SynthesisConfig {
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
}
