import { DecisionLayerConfigDto } from '../models/project-config.dto';
import { DecisionLayerConfig } from '../models/project-config.model';

const defaultDecisionLayerConfig = (): DecisionLayerConfig => ({
    mode: 'system',
    activeProvider: 'ollama',
    maxSteps: 4,
    releaseAfterUse: true,
    capabilities: {
        tool: false,
        vision: false,
        thinking: false,
    },
    providers: {
        ollama: {
                model: 'llama3.2',
                temperature: 0.2,
                maxTokens: 512,
                thinking: false,
        },
    },
    instructor: {
        buildSchema:
            '[CORE]\n{core}\n\n[RULES]\n{rules}\n\n[CONTEXT]\n{context}\n\n[MEMORY]\n{memory}\n\n[PERCEPTION]\n{perception}\n\n[SELF_STATE]\n{self_state}\n\n[OUTPUT]\nWrite the final user-facing reply using only relevant context.',
        includeDatetime: true,
        includeGeolocation: false,
        excludeDisabledModules: true,
    },
});

export const mapDecisionLayerDtoToModel = (
    dto?: Partial<DecisionLayerConfigDto> | null
): DecisionLayerConfig => {
    const defaults = defaultDecisionLayerConfig();
    const ollama: any = dto?.providers?.ollama || {};
    return {
        mode: dto?.mode === 'llm' ? 'llm' : 'system',
        activeProvider: dto?.active_provider || defaults.activeProvider,
        maxSteps: dto?.max_steps || defaults.maxSteps,
        releaseAfterUse: dto?.release_after_use ?? defaults.releaseAfterUse,
        capabilities: {
            ...defaults.capabilities,
            ...(dto?.capabilities || {}),
        },
        providers: {
            ...(dto?.providers || {}),
            ollama: {
                ...defaults.providers.ollama,
                ...ollama,
                maxTokens: ollama.max_tokens ?? defaults.providers.ollama.maxTokens,
            },
        },
        instructor: {
            ...defaults.instructor,
            buildSchema: dto?.instructor?.build_schema ?? defaults.instructor?.buildSchema ?? '',
            includeDatetime: dto?.instructor?.include_datetime ?? defaults.instructor?.includeDatetime ?? true,
            includeGeolocation: dto?.instructor?.include_geolocation ?? defaults.instructor?.includeGeolocation ?? false,
            excludeDisabledModules:
                dto?.instructor?.exclude_disabled_modules ?? defaults.instructor?.excludeDisabledModules ?? true,
        },
    };
};

export const mapDecisionLayerModelToDto = (
    model: Partial<DecisionLayerConfig>
): DecisionLayerConfigDto => {
    const defaults = defaultDecisionLayerConfig();
    const normalized = {
        ...defaults,
        ...(model || {}),
        capabilities: {
            ...defaults.capabilities,
            ...(model?.capabilities || {}),
        },
        providers: {
            ...defaults.providers,
            ...(model?.providers || {}),
            ollama: {
                ...defaults.providers.ollama,
                ...(model?.providers?.ollama || {}),
            },
        },
        instructor: {
            ...defaults.instructor,
            ...(model?.instructor || {}),
        },
    };

    return {
        mode: normalized.mode === 'llm' ? 'llm' : 'system',
        active_provider: normalized.activeProvider || 'ollama',
        max_steps: normalized.maxSteps || 4,
        release_after_use: normalized.releaseAfterUse ?? true,
        capabilities: {
            tool: !!normalized.capabilities.tool,
            vision: !!normalized.capabilities.vision,
            thinking: !!normalized.capabilities.thinking,
        },
        providers: {
            ...normalized.providers,
            ollama: {
                model: normalized.providers.ollama.model || 'llama3.2',
                temperature: normalized.providers.ollama.temperature ?? 0.2,
                max_tokens: normalized.providers.ollama.maxTokens ?? 512,
                thinking: normalized.providers.ollama.thinking ?? false,
            },
        },
        instructor: {
            build_schema: normalized.instructor?.buildSchema || defaults.instructor?.buildSchema || '',
            include_datetime: normalized.instructor?.includeDatetime ?? true,
            include_geolocation: normalized.instructor?.includeGeolocation ?? false,
            exclude_disabled_modules: normalized.instructor?.excludeDisabledModules ?? true,
        },
    };
};
