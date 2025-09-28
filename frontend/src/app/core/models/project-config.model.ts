export interface ProjectConfig {
    userId: string;
    charName: string;
    userName: string;
    language: string;
    voice: VoiceConfig;
    modules: ModuleConfig;
    vision: VisionConfig;
    audio: AudioConfig;
    rag: RagConfig;
    api: ApiConfig;
    openrouter: OpenRouterConfig;
    generateSettings: GenerationConfig;
    system: SystemConfig;
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
    voiceModules: Record<string, any>
}

export interface ModuleConfig {
    vtubeStudio: boolean;
    whisper: boolean;
    minecraft: boolean;
    gaming: boolean;
    alarm: boolean;
    discord: boolean;
    rag: boolean;
    visual: boolean;
}

export interface VisionModuleConfig {
    modelId: string;
    maxTokens: number;
}

export interface SystemConfig {
    userId: string;
    charName: string;
    userName: string;
    systemPrompt: string;
    language: string;
    theme: string;
}

export interface VisionConfig {
    enabled: boolean;
    activeProvider: string;              // ✅ было: active_provider
    monitorIndex: number;                // ✅ было: monitor_index
    fps: number;
    bufferSec: number;                   // ✅ было: buffer_sec
    downscaleWidth: number;              // ✅ было: downscale_width
    yoloEnabled: boolean;                // ✅ было: yolo_enabled
    ocrLang: string;                     // ✅ было: ocr_lang
    ocrMinConf: number;                  // ✅ было: ocr_min_conf
    ocrMaxLines: number;                 // ✅ было: ocr_max_lines
    region: any;
    captureMode: string;                 // ✅ было: capture_mode
    windowTitle: string;                 // ✅ было: window_title
    windowProcess: string;               // ✅ было: window_process
    debugSave: boolean;                  // ✅ было: debug_save
    debugPath: string;                   // ✅ было: debug_path
    visionModules: {                    // ✅ было: vision_modules
        [key: string]: VisionModuleConfig;
    };
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
}

export interface ApiConfig {
    type: string;
    streaming: boolean;
    model: string;
    visualModel: string;
    tokenLimit: number;
    messagePairLimit: number;
}

export interface OpenRouterConfig {
    apiKey?: string;
    model?: string;
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
