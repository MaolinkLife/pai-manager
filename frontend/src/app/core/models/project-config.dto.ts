export interface ProjectConfigDto {
    char_name: string;
    user_name: string;
    language: string;
    voice: {
        enabled: boolean;
        output_id: number;
        windows_output_id: number;
        language: string;
        use_rvc: boolean;
        voice_language: string;
    };
    modules: {
        vtube_studio: boolean;
        whisper: boolean;
        minecraft: boolean;
        gaming: boolean;
        alarm: boolean;
        discord: boolean;
        rag: boolean;
        visual: boolean;
    };
    api: {
        type: string;
        streaming: boolean;
        model: string;
        visual_model: string;
        token_limit: number;
        message_pair_limit: number;
    };
}
