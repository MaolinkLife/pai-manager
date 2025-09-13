import { ProjectConfigDto } from '../models/project-config.dto';
import { ProjectConfig } from '../models/project-config.model';

export const mapProjectConfigDtoToModel = (dto: ProjectConfigDto): ProjectConfig => ({
    userId: dto.user_id,
    charName: dto.char_name,
    userName: dto.user_name,
    language: dto.language,
    voice: {
        enabled: dto.voice.enabled,
        outputId: dto.voice.output_id,
        windowsOutputId: dto.voice.windows_output_id,
        language: dto.voice.language,
        useRvc: dto.voice.use_rvc,
        voiceLanguage: dto.voice.voice_language,
        useWindowsOutput: dto.voice.use_windows_output,
        streamingTts: dto.voice.streaming_tts,
    },
    modules: {
        vtubeStudio: dto.modules.vtube_studio,
        whisper: dto.modules.whisper,
        minecraft: dto.modules.minecraft,
        gaming: dto.modules.gaming,
        alarm: dto.modules.alarm,
        discord: dto.modules.discord,
        rag: dto.modules.rag,
        visual: dto.modules.visual,
    },
    vision: {
        enabled: dto.vision.enabled,
        monitorIndex: dto.vision.monitor_index,
        fps: dto.vision.fps,
        bufferSec: dto.vision.buffer_sec,
        downscaleWidth: dto.vision.downscale_width,
        yoloEnabled: dto.vision.yolo_enabled,
        ocrLang: dto.vision.ocr_lang,
        ocrMinConf: dto.vision.ocr_min_conf,
        ocrMaxLines: dto.vision.ocr_max_lines,
        region: dto.vision.region,
    },
    audio: {
        inputDevice: dto.audio?.input_device,
        outputDevice: dto.audio?.output_device,
        sampleRate: dto.audio?.sample_rate,
        bufferSize: dto.audio?.buffer_size,
        enableNoiseReduction: dto.audio?.enable_noise_reduction,
        enableEchoCancellation: dto.audio?.enable_echo_cancellation,
        volumeThreshold: dto.audio?.volume_threshold,
        silenceDuration: dto.audio?.silence_duration,
    },
    rag: {
        enabled: dto.rag?.enabled ?? false,
        embeddingModel: dto.rag?.embedding_model,
        vectorDbPath: dto.rag?.vector_db_path,
        chunkSize: dto.rag?.chunk_size,
        chunkOverlap: dto.rag?.chunk_overlap,
        topK: dto.rag?.top_k,
        similarityThreshold: dto.rag?.similarity_threshold,
        enableCaching: dto.rag?.enable_caching,
        cacheTtl: dto.rag?.cache_ttl,
    },
    openrouter: {
        apiKey: dto.openrouter?.api_key,
        model: dto.openrouter?.model,
    },
    api: {
        type: dto.api.type,
        streaming: dto.api.streaming,
        model: dto.api.model,
        visualModel: dto.api.visual_model,
        tokenLimit: dto.api.token_limit,
        messagePairLimit: dto.api.message_pair_limit,
    },
    generateSettings: {
        temperature: dto.generate_settings.temperature,
        minP: dto.generate_settings.min_p,
        topP: dto.generate_settings.top_p,
        topK: dto.generate_settings.top_k,
        repeatPenalty: dto.generate_settings.repeat_penalty,
        stop: dto.generate_settings.stop,
        numPredict: dto.generate_settings.num_predict,
        name: dto.generate_settings.name,
        description: dto.generate_settings.description,
    },
});

export const mapProjectConfigModelToDto = (model: ProjectConfig): ProjectConfigDto => ({
    user_id: model.userId,
    char_name: model.charName,
    user_name: model.userName,
    language: model.language,
    voice: {
        enabled: model.voice.enabled,
        output_id: model.voice.outputId,
        windows_output_id: model.voice.windowsOutputId,
        language: model.voice.language,
        use_rvc: model.voice.useRvc,
        voice_language: model.voice.voiceLanguage,
        use_windows_output: model.voice.useWindowsOutput,
        streaming_tts: model.voice.streamingTts,
    },
    modules: {
        vtube_studio: model.modules.vtubeStudio,
        whisper: model.modules.whisper,
        minecraft: model.modules.minecraft,
        gaming: model.modules.gaming,
        alarm: model.modules.alarm,
        discord: model.modules.discord,
        rag: model.modules.rag,
        visual: model.modules.visual,
    },
    vision: {
        enabled: model.vision.enabled,
        monitor_index: model.vision.monitorIndex,
        fps: model.vision.fps,
        buffer_sec: model.vision.bufferSec,
        downscale_width: model.vision.downscaleWidth,
        yolo_enabled: model.vision.yoloEnabled,
        ocr_lang: model.vision.ocrLang,
        ocr_min_conf: model.vision.ocrMinConf,
        ocr_max_lines: model.vision.ocrMaxLines,
        region: model.vision.region,
    },
    audio: {
        input_device: model.audio.inputDevice,
        output_device: model.audio.outputDevice,
        sample_rate: model.audio.sampleRate,
        buffer_size: model.audio.bufferSize,
        enable_noise_reduction: model.audio.enableNoiseReduction,
        enable_echo_cancellation: model.audio.enableEchoCancellation,
        volume_threshold: model.audio.volumeThreshold,
        silence_duration: model.audio.silenceDuration,
    },
    rag: {
        enabled: model.rag.enabled,
        embedding_model: model.rag.embeddingModel,
        vector_db_path: model.rag.vectorDbPath,
        chunk_size: model.rag.chunkSize,
        chunk_overlap: model.rag.chunkOverlap,
        top_k: model.rag.topK,
        similarity_threshold: model.rag.similarityThreshold,
        enable_caching: model.rag.enableCaching,
        cache_ttl: model.rag.cacheTtl,
    },
    openrouter: {
        api_key: model.openrouter?.apiKey,
        model: model.openrouter?.model,
    },
    api: {
        type: model.api.type,
        streaming: model.api.streaming,
        model: model.api.model,
        visual_model: model.api.visualModel,
        token_limit: model.api.tokenLimit,
        message_pair_limit: model.api.messagePairLimit,
    },
    generate_settings: {
        temperature: model.generateSettings.temperature,
        min_p: model.generateSettings.minP,
        top_p: model.generateSettings.topP,
        top_k: model.generateSettings.topK,
        repeat_penalty: model.generateSettings.repeatPenalty,
        stop: model.generateSettings.stop,
        num_predict: model.generateSettings.numPredict,
        name: model.generateSettings.name,
        description: model.generateSettings.description,
    },
});

export const mapPartialModelToDto = (
    model: Partial<ProjectConfig>
): Partial<ProjectConfigDto> => {
    const dto: Partial<ProjectConfigDto> = {};

    Object.keys(model).forEach((key) => {
        switch (key) {
            case 'userId':
                dto.user_id = model.userId;
                break;
            case 'charName':
                dto.char_name = model.charName;
                break;
            case 'userName':
                dto.user_name = model.userName;
                break;
            case 'language':
                dto.language = model.language;
                break;
            case 'voice':
                dto.voice = mapVoiceModelToDto(model.voice!);
                break;
            case 'modules':
                dto.modules = mapModulesModelToDto(model.modules!);
                break;
            case 'vision':
                dto.vision = mapVisionModelToDto(model.vision!);
                break;
            case 'audio':
                dto.audio = mapAudioModelToDto(model.audio!);
                break;
            case 'rag':
                dto.rag = mapRagModelToDto(model.rag!);
                break;
            case 'openrouter':
                dto.openrouter = mapOpenRouterModelToDto(model.openrouter!);
                break;
            case 'api':
                dto.api = mapApiModelToDto(model.api!);
                break;
            case 'generateSettings':
                dto.generate_settings = mapGenerationModelToDto(model.generateSettings!);
                break;
        }
    });

    return dto;
};

// Individual mappers
const mapVoiceModelToDto = (voice: ProjectConfig['voice']) => ({
    enabled: voice.enabled,
    output_id: voice.outputId,
    windows_output_id: voice.windowsOutputId,
    language: voice.language,
    use_rvc: voice.useRvc,
    voice_language: voice.voiceLanguage,
    use_windows_output: voice.useWindowsOutput,
    streaming_tts: voice.streamingTts,
});

const mapModulesModelToDto = (modules: ProjectConfig['modules']) => ({
    vtube_studio: modules.vtubeStudio,
    whisper: modules.whisper,
    minecraft: modules.minecraft,
    gaming: modules.gaming,
    alarm: modules.alarm,
    discord: modules.discord,
    rag: modules.rag,
    visual: modules.visual,
});

const mapVisionModelToDto = (vision: ProjectConfig['vision']) => ({
    enabled: vision.enabled,
    monitor_index: vision.monitorIndex,
    fps: vision.fps,
    buffer_sec: vision.bufferSec,
    downscale_width: vision.downscaleWidth,
    yolo_enabled: vision.yoloEnabled,
    ocr_lang: vision.ocrLang,
    ocr_min_conf: vision.ocrMinConf,
    ocr_max_lines: vision.ocrMaxLines,
    region: vision.region,
});

const mapAudioModelToDto = (audio: ProjectConfig['audio']) => ({
    input_device: audio.inputDevice,
    output_device: audio.outputDevice,
    sample_rate: audio.sampleRate,
    buffer_size: audio.bufferSize,
    enable_noise_reduction: audio.enableNoiseReduction,
    enable_echo_cancellation: audio.enableEchoCancellation,
    volume_threshold: audio.volumeThreshold,
    silence_duration: audio.silenceDuration,
});

const mapRagModelToDto = (rag: ProjectConfig['rag']) => ({
    enabled: rag.enabled,
    embedding_model: rag.embeddingModel,
    vector_db_path: rag.vectorDbPath,
    chunk_size: rag.chunkSize,
    chunk_overlap: rag.chunkOverlap,
    top_k: rag.topK,
    similarity_threshold: rag.similarityThreshold,
    enable_caching: rag.enableCaching,
    cache_ttl: rag.cacheTtl,
});

const mapOpenRouterModelToDto = (openrouter: ProjectConfig['openrouter']) => ({
    api_key: openrouter.apiKey,
    model: openrouter.model,
});

const mapApiModelToDto = (api: ProjectConfig['api']) => ({
    type: api.type,
    streaming: api.streaming,
    model: api.model,
    visual_model: api.visualModel,
    token_limit: api.tokenLimit,
    message_pair_limit: api.messagePairLimit,
});

const mapGenerationModelToDto = (generation: ProjectConfig['generateSettings']) => ({
    temperature: generation.temperature,
    min_p: generation.minP,
    top_p: generation.topP,
    top_k: generation.topK,
    repeat_penalty: generation.repeatPenalty,
    stop: generation.stop,
    num_predict: generation.numPredict,
    name: generation.name,
    description: generation.description,
});
