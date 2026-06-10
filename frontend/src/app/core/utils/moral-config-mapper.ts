import {
    MoralConfigDto,
    MoralDecayConfigDto,
    MoralForgivenessConfigDto,
    MoralInnerVoiceConfigDto,
    MoralProviderConfigDto,
    MoralScarTriggerDto,
    MoralScarsConfigDto,
} from '../models/project-config.dto';
import {
    MoralConfig,
    MoralDecayConfig,
    MoralForgivenessConfig,
    MoralInnerVoiceConfig,
    MoralProviderConfig,
    MoralScarTrigger,
    MoralScarsConfig,
} from '../models/project-config.model';

const mapDecayDtoToModel = (dto?: MoralDecayConfigDto): MoralDecayConfig | undefined => {
    if (!dto) {
        return undefined;
    }
    return {
        enabled: dto.enabled ?? true,
        globalRate: dto.global_rate ?? 0.05,
    };
};

const mapDecayModelToDto = (model?: MoralDecayConfig): MoralDecayConfigDto | undefined => {
    if (!model) {
        return undefined;
    }
    return {
        enabled: model.enabled,
        global_rate: model.globalRate,
    };
};

const mapForgivenessDtoToModel = (
    dto?: MoralForgivenessConfigDto,
): MoralForgivenessConfig | undefined => {
    if (!dto) {
        return undefined;
    }
    return {
        enabled: dto.enabled ?? true,
        compensatingTones: dto.compensating_tones ?? [],
        softenableEmotions: dto.softenable_emotions ?? [],
        deltaPerEvent: dto.delta_per_event ?? 0.1,
        lookbackDays: dto.lookback_days ?? 14,
    };
};

const mapForgivenessModelToDto = (
    model?: MoralForgivenessConfig,
): MoralForgivenessConfigDto | undefined => {
    if (!model) {
        return undefined;
    }
    return {
        enabled: model.enabled,
        compensating_tones: model.compensatingTones,
        softenable_emotions: model.softenableEmotions,
        delta_per_event: model.deltaPerEvent,
        lookback_days: model.lookbackDays,
    };
};

const mapScarTriggerDtoToModel = (dto: MoralScarTriggerDto): MoralScarTrigger => ({
    name: dto.name ?? '',
    intents: dto.intents ?? [],
    tones: dto.tones ?? [],
    keywords: dto.keywords ?? [],
    persistenceFloor: dto.persistence_floor ?? 0.4,
    intensityBoost: dto.intensity_boost ?? 0.2,
});

const mapScarTriggerModelToDto = (model: MoralScarTrigger): MoralScarTriggerDto => ({
    name: model.name,
    intents: model.intents,
    tones: model.tones,
    keywords: model.keywords,
    persistence_floor: model.persistenceFloor,
    intensity_boost: model.intensityBoost,
});

const mapScarsDtoToModel = (dto?: MoralScarsConfigDto): MoralScarsConfig | undefined => {
    if (!dto) {
        return undefined;
    }
    return {
        enabled: dto.enabled ?? false,
        triggers: (dto.triggers ?? []).map(mapScarTriggerDtoToModel),
    };
};

const mapScarsModelToDto = (model?: MoralScarsConfig): MoralScarsConfigDto | undefined => {
    if (!model) {
        return undefined;
    }
    return {
        enabled: model.enabled,
        triggers: (model.triggers ?? []).map(mapScarTriggerModelToDto),
    };
};

const mapInnerVoiceDtoToModel = (
    dto?: MoralInnerVoiceConfigDto,
): MoralInnerVoiceConfig | undefined => {
    if (!dto) {
        return undefined;
    }
    return {
        enabled: dto.enabled ?? true,
        maxTokens: dto.max_tokens ?? 80,
        temperature: dto.temperature ?? 0.7,
        language: dto.language ?? '',
    };
};

const mapInnerVoiceModelToDto = (
    model?: MoralInnerVoiceConfig,
): MoralInnerVoiceConfigDto | undefined => {
    if (!model) {
        return undefined;
    }
    return {
        enabled: model.enabled,
        max_tokens: model.maxTokens,
        temperature: model.temperature,
        language: model.language,
    };
};

const mapProviderDtoToModel = (dto?: MoralProviderConfigDto): MoralProviderConfig | undefined => {
    if (!dto) {
        return undefined;
    }
    return {
        apiKey: dto.api_key,
        model: dto.model,
        temperature: dto.temperature,
        maxTokens: dto.max_tokens,
        thinking: dto.thinking,
        enabled: dto.enabled,
        baseUrl: dto.base_url,
        requestTimeout: dto.request_timeout,
    };
};

const mapProviderModelToDto = (config?: MoralProviderConfig): MoralProviderConfigDto | undefined => {
    if (!config) {
        return undefined;
    }
    return {
        api_key: config.apiKey,
        model: config.model,
        temperature: config.temperature,
        max_tokens: config.maxTokens,
        thinking: config.thinking,
        enabled: config.enabled,
        base_url: config.baseUrl,
        request_timeout: config.requestTimeout,
    };
};

export const mapMoralDtoToModel = (dto?: MoralConfigDto): MoralConfig => ({
    enabled: dto?.enabled ?? true,
    activeProvider: dto?.active_provider ?? 'heuristic',
    fallbackOrder: dto?.fallback_order ?? [],
    releaseAfterUse: dto?.release_after_use ?? true,
    systemPrompt: dto?.system_prompt ?? '',
    providers: {
        heuristic: dto?.providers?.heuristic ?? {},
        ollama: mapProviderDtoToModel(dto?.providers?.ollama),
        openrouter: mapProviderDtoToModel(dto?.providers?.openrouter),
        llamaCpp: mapProviderDtoToModel(dto?.providers?.llama_cpp),
    },
    decay: mapDecayDtoToModel(dto?.decay),
    forgiveness: mapForgivenessDtoToModel(dto?.forgiveness),
    scars: mapScarsDtoToModel(dto?.scars),
    innerVoice: mapInnerVoiceDtoToModel(dto?.inner_voice),
});

export const mapMoralModelToDto = (model?: MoralConfig): MoralConfigDto => {
    const dto: MoralConfigDto = {
        enabled: model?.enabled ?? true,
        active_provider: model?.activeProvider ?? 'heuristic',
        fallback_order: model?.fallbackOrder ?? [],
        release_after_use: model?.releaseAfterUse ?? true,
        system_prompt: model?.systemPrompt ?? '',
        providers: {
            heuristic: model?.providers?.heuristic ?? {},
            ollama: mapProviderModelToDto(model?.providers?.ollama),
            openrouter: mapProviderModelToDto(model?.providers?.openrouter),
            llama_cpp: mapProviderModelToDto(model?.providers?.llamaCpp),
        },
    };
    const decayDto = mapDecayModelToDto(model?.decay);
    if (decayDto) {
        dto.decay = decayDto;
    }
    const forgivenessDto = mapForgivenessModelToDto(model?.forgiveness);
    if (forgivenessDto) {
        dto.forgiveness = forgivenessDto;
    }
    const scarsDto = mapScarsModelToDto(model?.scars);
    if (scarsDto) {
        dto.scars = scarsDto;
    }
    const innerVoiceDto = mapInnerVoiceModelToDto(model?.innerVoice);
    if (innerVoiceDto) {
        dto.inner_voice = innerVoiceDto;
    }
    return dto;
};

export const mapMoralPartialModelToDto = (
    model?: Partial<MoralConfig>
): Partial<MoralConfigDto> | undefined => {
    if (!model) {
        return undefined;
    }

    const dto: Partial<MoralConfigDto> = {};

    if (model.enabled !== undefined) {
        dto.enabled = model.enabled;
    }

    if (model.activeProvider !== undefined) {
        dto.active_provider = model.activeProvider;
    }

    if (model.fallbackOrder !== undefined) {
        dto.fallback_order = model.fallbackOrder;
    }

    if (model.releaseAfterUse !== undefined) {
        dto.release_after_use = model.releaseAfterUse;
    }

    if (model.systemPrompt !== undefined) {
        dto.system_prompt = model.systemPrompt;
    }

    if (model.providers !== undefined) {
        const providersDto: Partial<MoralConfigDto['providers']> = {};
        const providers = model.providers;

        if (providers.heuristic !== undefined) {
            providersDto.heuristic = providers.heuristic;
        }

        if (providers.ollama !== undefined) {
            const ollama = providers.ollama;
            if (ollama) {
                providersDto.ollama = {};
                if (ollama.model !== undefined) {
                    providersDto.ollama.model = ollama.model;
                }
                if (ollama.temperature !== undefined) {
                    providersDto.ollama.temperature = ollama.temperature;
                }
                if (ollama.maxTokens !== undefined) {
                    providersDto.ollama.max_tokens = ollama.maxTokens;
                }
                if (ollama.thinking !== undefined) {
                    providersDto.ollama.thinking = ollama.thinking;
                }
            } else {
                providersDto.ollama = undefined;
            }
        }

        if (providers.openrouter !== undefined) {
            const openrouter = providers.openrouter;
            if (openrouter) {
                providersDto.openrouter = {};
                if (openrouter.apiKey !== undefined) {
                    providersDto.openrouter.api_key = openrouter.apiKey;
                }
                if (openrouter.model !== undefined) {
                    providersDto.openrouter.model = openrouter.model;
                }
                if (openrouter.temperature !== undefined) {
                    providersDto.openrouter.temperature = openrouter.temperature;
                }
                if (openrouter.maxTokens !== undefined) {
                    providersDto.openrouter.max_tokens = openrouter.maxTokens;
                }
            } else {
                providersDto.openrouter = undefined;
            }
        }

        if (providers.llamaCpp !== undefined) {
            const llamaCpp = providers.llamaCpp;
            if (llamaCpp) {
                providersDto.llama_cpp = {};
                if (llamaCpp.enabled !== undefined) {
                    providersDto.llama_cpp.enabled = llamaCpp.enabled;
                }
                if (llamaCpp.baseUrl !== undefined) {
                    providersDto.llama_cpp.base_url = llamaCpp.baseUrl;
                }
                if (llamaCpp.model !== undefined) {
                    providersDto.llama_cpp.model = llamaCpp.model;
                }
                if (llamaCpp.temperature !== undefined) {
                    providersDto.llama_cpp.temperature = llamaCpp.temperature;
                }
                if (llamaCpp.maxTokens !== undefined) {
                    providersDto.llama_cpp.max_tokens = llamaCpp.maxTokens;
                }
                if (llamaCpp.requestTimeout !== undefined) {
                    providersDto.llama_cpp.request_timeout = llamaCpp.requestTimeout;
                }
            } else {
                providersDto.llama_cpp = undefined;
            }
        }

        if (Object.keys(providersDto).length > 0) {
            dto.providers = providersDto as MoralConfigDto['providers'];
        }
    }

    if (model.decay !== undefined) {
        dto.decay = mapDecayModelToDto(model.decay);
    }
    if (model.forgiveness !== undefined) {
        dto.forgiveness = mapForgivenessModelToDto(model.forgiveness);
    }
    if (model.scars !== undefined) {
        dto.scars = mapScarsModelToDto(model.scars);
    }
    if (model.innerVoice !== undefined) {
        dto.inner_voice = mapInnerVoiceModelToDto(model.innerVoice);
    }

    return Object.keys(dto).length > 0 ? dto : undefined;
};
