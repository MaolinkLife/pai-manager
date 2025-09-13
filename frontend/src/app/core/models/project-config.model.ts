export interface ProjectConfig {
    userId?: string;
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

export interface VisionConfig {
    enabled: boolean;
    monitorIndex: number;
    fps: number;
    bufferSec: number;
    downscaleWidth: number;
    yoloEnabled: boolean;
    ocrLang: string;
    ocrMinConf: number;
    ocrMaxLines: number;
    region: any;
}

export interface AudioConfig {
    inputDevice?: string;
    outputDevice?: string;
    sampleRate?: number;
    bufferSize?: number;
    enableNoiseReduction?: boolean;
    enableEchoCancellation?: boolean;
    volumeThreshold?: number;
    silenceDuration?: number;
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
