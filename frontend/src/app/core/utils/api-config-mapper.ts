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
        visualModel: dto.visual_model,
        visualModelOptions: dto.visual_model_options ?? [],
        tokenLimit: dto.token_limit,
        messagePairLimit: dto.message_pair_limit,
        activeProvider,
        fallbackOrder: dto.fallback_order ?? [],
        providers,
    };
};

export const mapApiModelToDto = (api: ProjectConfig['api']) => {
    const providers: Record<string, any> = {};
    Object.keys(api.providers ?? {}).forEach((key: string) => {
        const value = api.providers?.[key];
        if (!value) {
            return;
        }
        const providerModel = api.activeProvider === key ? api.model : value.model;
        providers[key] = {
            ...value,
            model: providerModel,
            temperature: value.temperature,
            max_tokens: value.maxTokens,
            streaming: value.streaming,
            api_key: value.apiKey,
            base_url: value.baseUrl,
        };
        delete providers[key].maxTokens;
        delete providers[key].apiKey;
        delete providers[key].baseUrl;
    });

    return {
        type: api.type,
        streaming: api.streaming,
        model: api.model,
        visual_model: api.visualModel,
        visual_model_options: api.visualModelOptions ?? [],
        token_limit: api.tokenLimit,
        message_pair_limit: api.messagePairLimit,
        active_provider: api.activeProvider,
        fallback_order: api.fallbackOrder,
        providers,
    };
};
