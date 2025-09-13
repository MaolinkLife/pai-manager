export interface ProjectConfigDto {
    user_id?: string;
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
        use_windows_output: boolean;
        streaming_tts: boolean;
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
    vision: {
        enabled: boolean;
        monitor_index: number;
        fps: number;
        buffer_sec: number;
        downscale_width: number;
        yolo_enabled: boolean;
        ocr_lang: string;
        ocr_min_conf: number;
        ocr_max_lines: number;
        region: any;
    };
    audio: {
        input_device?: string;
        output_device?: string;
        sample_rate?: number;
        buffer_size?: number;
        enable_noise_reduction?: boolean;
        enable_echo_cancellation?: boolean;
        volume_threshold?: number;
        silence_duration?: number;
    };
    rag: {
        enabled: boolean;
        embedding_model?: string;
        vector_db_path?: string;
        chunk_size?: number;
        chunk_overlap?: number;
        top_k?: number;
        similarity_threshold?: number;
        enable_caching?: boolean;
        cache_ttl?: number;
    };
    openrouter: {
        api_key?: string;
        model?: string;
    };
    api: {
        type: string;
        streaming: boolean;
        model: string;
        visual_model: string;
        token_limit: number;
        message_pair_limit: number;
    };
    generate_settings: {
        temperature: number;
        min_p: number;
        top_p: number;
        top_k: number;
        repeat_penalty: number;
        stop: string[] | null;
        num_predict: number;
        name?: string;
        description?: string;
    };
}
