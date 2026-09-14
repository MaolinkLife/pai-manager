import { DecisionLayerConfigDto } from '../models/project-config.dto';
import { DecisionLayerConfig } from '../models/project-config.model';
import { promptField } from './technical-prompt-field';

const defaultDecisionLayerConfig = (): DecisionLayerConfig => ({
    mode: 'system',
    activeProvider: 'ollama',
    maxSteps: 4,
    releaseAfterUse: true,
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
        orchestratorPrompt: dto?.orchestrator_prompt ?? '',
    };
};

export const mapDecisionLayerModelToDto = (
    model: Partial<DecisionLayerConfig>
): DecisionLayerConfigDto => {
    const defaults = defaultDecisionLayerConfig();
    const normalized = {
        ...defaults,
        ...(model || {}),
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
        ...promptField('orchestrator_prompt', model?.orchestratorPrompt),
    };
};

const putDefined = (target: Record<string, any>, key: string, value: unknown): void => {
    if (value !== undefined) {
        target[key] = value;
    }
};

/**
 * A settings save sends only the fields it changed. Filling the rest with the
 * frontend defaults overwrote the saved mode and model on every
 * save of the Core tab.
 */
export const mapDecisionLayerPartialModelToDto = (
    model: Partial<DecisionLayerConfig> | undefined,
): Partial<DecisionLayerConfigDto> => {
    const dto: Record<string, any> = {};
    if (!model) {
        return dto;
    }
    if (model.mode !== undefined) {
        dto['mode'] = model.mode === 'llm' ? 'llm' : 'system';
    }
    putDefined(dto, 'active_provider', model.activeProvider);
    putDefined(dto, 'max_steps', model.maxSteps);
    putDefined(dto, 'release_after_use', model.releaseAfterUse);

    if (model.providers) {
        const providers: Record<string, any> = {};
        Object.entries(model.providers).forEach(([name, provider]) => {
            if (name !== 'ollama') {
                providers[name] = provider;
                return;
            }
            const ollama: Record<string, any> = {};
            putDefined(ollama, 'model', provider?.model);
            putDefined(ollama, 'temperature', provider?.temperature);
            putDefined(ollama, 'max_tokens', provider?.maxTokens);
            putDefined(ollama, 'thinking', provider?.thinking);
            providers['ollama'] = ollama;
        });
        dto['providers'] = providers;
    }

    if (model.instructor) {
        const instructor: Record<string, any> = {};
        putDefined(instructor, 'build_schema', model.instructor.buildSchema);
        putDefined(instructor, 'include_datetime', model.instructor.includeDatetime);
        putDefined(instructor, 'include_geolocation', model.instructor.includeGeolocation);
        putDefined(instructor, 'exclude_disabled_modules', model.instructor.excludeDisabledModules);
        dto['instructor'] = instructor;
    }

    Object.assign(dto, promptField('orchestrator_prompt', model.orchestratorPrompt));
    return dto as Partial<DecisionLayerConfigDto>;
};
