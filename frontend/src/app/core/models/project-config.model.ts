export interface ProjectConfig {
    charName: string;
    userName: string;
    voice: VoiceConfig;
    modules: ModuleConfig;
    api: ApiConfig;
}

export interface VoiceConfig {
    outputId: number;
    windowsOutputId: number;
    language: string;
    useRvc: boolean;
    voiceLanguage: string;
}

export interface ModuleConfig {
    vtube_studio: boolean;
    whisper: boolean;
    minecraft: boolean;
    gaming: boolean;
    alarm: boolean;
    discord: boolean;
    rag: boolean;
    visual: boolean;
}

export interface ApiConfig {
    type: string;
    streaming: boolean;
    model: string;
    visualModel: string;
    tokenLimit: number;
    messagePairLimit: number;
}
