import { ProjectConfig } from '../models/project-config.model';

const snakeToCamel = (str: string): string =>
    str.replace(/_([a-z])/g, (match, letter: string) => letter.toUpperCase());

const camelToSnake = (str: string): string =>
    str.replace(/([A-Z])/g, '_$1').toLowerCase();

const deepMapKeys = (value: any, mapper: (key: string) => string): any => {
    if (Array.isArray(value)) {
        return value.map((item) => deepMapKeys(item, mapper));
    }

    if (value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
        const result: any = {};
        Object.keys(value).forEach((key) => {
            result[mapper(key)] = deepMapKeys(value[key], mapper);
        });
        return result;
    }

    return value;
};

export const mapVoiceDtoToModel = (dto: any) => {
    const modulesDto = dto?.voice_modules ?? dto?.voiceModules;
    const rvcDto = dto?.rvc;
    const model: any = {
        enabled: dto.enabled,
        outputId: dto.output_id ?? dto.outputId,
        windowsOutputId: dto.windows_output_id ?? dto.windowsOutputId,
        language: dto.language,
        useRvc: dto.use_rvc ?? dto.useRvc,
        voiceLanguage: dto.voice_language ?? dto.voiceLanguage,
        useWindowsOutput: dto.use_windows_output ?? dto.useWindowsOutput,
        streamingTts: dto.streaming_tts ?? dto.streamingTts,
        enableFallback: dto.enable_fallback ?? dto.enableFallback,
        activeModule: dto.active_module ?? dto.activeModule,
    };

    if (rvcDto) {
        model.rvc = deepMapKeys(rvcDto, snakeToCamel);
    }

    if (modulesDto) {
        model.voiceModules = deepMapKeys(modulesDto, snakeToCamel);
    }

    return model;
};

export const mapVoiceModelToDto = (voice: ProjectConfig['voice']) => {
    const dto: any = {
        enabled: voice.enabled,
        output_id: voice.outputId,
        windows_output_id: voice.windowsOutputId,
        language: voice.language,
        use_rvc: voice.useRvc,
        voice_language: voice.voiceLanguage,
        use_windows_output: voice.useWindowsOutput,
        streaming_tts: voice.streamingTts,
        enable_fallback: voice.enableFallback,
        active_module: voice.activeModule,
    };

    if (voice.voiceModules) {
        dto.voice_modules = deepMapKeys(voice.voiceModules, camelToSnake);
    }

    if ((voice as any).rvc) {
        dto.rvc = deepMapKeys((voice as any).rvc, camelToSnake);
    }

    return dto;
};
