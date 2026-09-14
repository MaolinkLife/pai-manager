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

const VOICE_FIELD_NAMES: Array<[string, string]> = [
    ['enabled', 'enabled'],
    ['outputId', 'output_id'],
    ['windowsOutputId', 'windows_output_id'],
    ['language', 'language'],
    ['useRvc', 'use_rvc'],
    ['voiceLanguage', 'voice_language'],
    ['useWindowsOutput', 'use_windows_output'],
    ['streamingTts', 'streaming_tts'],
    ['enableFallback', 'enable_fallback'],
    ['activeModule', 'active_module'],
];

/** A settings save sends only the fields it carries — nothing is filled in. */
export const mapVoiceModelToDto = (voice: Partial<ProjectConfig['voice']>) => {
    const dto: any = {};
    VOICE_FIELD_NAMES.forEach(([from, to]) => {
        const value = (voice as Record<string, unknown>)[from];
        if (value !== undefined) {
            dto[to] = value;
        }
    });

    if (voice.voiceModules) {
        dto.voice_modules = deepMapKeys(voice.voiceModules, camelToSnake);
    }

    if ((voice as any).rvc) {
        dto.rvc = deepMapKeys((voice as any).rvc, camelToSnake);
    }

    return dto;
};
