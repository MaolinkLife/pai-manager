import { ProjectConfigDto } from '../models/project-config.dto';
import { ProjectConfig } from '../models/project-config.model';

export const mapApiDtoToModel = (dto: any) => {
    const rawProviders = dto.providers ?? {};
    const providers: Record<string, any> = {};
    Object.keys(rawProviders).forEach((key: string) => {
        const value = rawProviders[key] ?? {};
        providers[key] = {
            ...value,
            model: value.model,
            temperature: value.temperature,
            maxTokens: value.max_tokens,
            streaming: value.streaming,
            apiKey: value.api_key,
            baseUrl: value.base_url,
        };
        delete providers[key].max_tokens;
        delete providers[key].api_key;
        delete providers[key].base_url;
    });

    const activeProvider = dto.active_provider;
    const syncedModel = providers?.[activeProvider]?.model ?? dto.model;

    return {
        type: dto.type,
        streaming: dto.streaming,
        model: syncedModel,
        tokenLimit: dto.token_limit,
        messagePairLimit: dto.message_pair_limit,
        activeProvider,
        fallbackOrder: dto.fallback_order ?? [],
        providers,
    };
};

const API_FIELD_NAMES: Array<[string, string]> = [
    ['type', 'type'],
    ['streaming', 'streaming'],
    ['model', 'model'],
    ['tokenLimit', 'token_limit'],
    ['messagePairLimit', 'message_pair_limit'],
    ['activeProvider', 'active_provider'],
    ['fallbackOrder', 'fallback_order'],
];

const PROVIDER_FIELD_NAMES: Array<[string, string]> = [
    ['maxTokens', 'max_tokens'],
    ['apiKey', 'api_key'],
    ['baseUrl', 'base_url'],
];

/** A settings save sends only the fields it carries — nothing is filled in. */
export const mapApiModelToDto = (api: Partial<ProjectConfig['api']>): ProjectConfigDto['api'] => {
    const dto: Record<string, any> = {};
    API_FIELD_NAMES.forEach(([from, to]) => {
        const value = (api as Record<string, any>)[from];
        if (value !== undefined) {
            dto[to] = value;
        }
    });

    if (api.providers) {
        const providers: Record<string, any> = {};
        Object.keys(api.providers).forEach((key: string) => {
            const value = api.providers?.[key];
            if (!value) {
                return;
            }
            const provider: Record<string, any> = { ...value };
            PROVIDER_FIELD_NAMES.forEach(([from, to]) => {
                if (from in provider) {
                    if (provider[from] !== undefined) {
                        provider[to] = provider[from];
                    }
                    delete provider[from];
                }
            });
            // The active provider's model follows api.model when the save carries both.
            if (api.activeProvider === key && api.model !== undefined) {
                provider['model'] = api.model;
            }
            providers[key] = provider;
        });
        dto['providers'] = providers;
    }

    return dto as ProjectConfigDto['api'];
};
