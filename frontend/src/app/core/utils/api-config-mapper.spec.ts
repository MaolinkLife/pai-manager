import { mapApiModelToDto } from './api-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';

describe('api config mapper: partial saves', () => {
    it('sends only the fields it carries', () => {
        expect(mapApiModelToDto({ providers: { ollama: { temperature: 0.5 } } } as any)).toEqual({
            providers: { ollama: { temperature: 0.5 } },
        } as any);
        expect(mapApiModelToDto({ streaming: false })).toEqual({ streaming: false } as any);
    });

    it('renames provider fields for the server', () => {
        expect(mapApiModelToDto({ providers: { openrouter: { apiKey: 'k', baseUrl: 'u', maxTokens: 10 } } } as any)).toEqual({
            providers: { openrouter: { api_key: 'k', base_url: 'u', max_tokens: 10 } },
        } as any);
    });

    it('keeps the active provider model in step with api.model when both are saved', () => {
        const dto: any = mapApiModelToDto({ activeProvider: 'ollama', model: 'llama3.2', providers: { ollama: { model: 'old' } } } as any);

        expect(dto.providers.ollama.model).toBe('llama3.2');
    });

    it('a model change reaches the server without its neighbours', () => {
        expect(mapPartialModelToDto({ api: { model: 'llama3.2', providers: { ollama: { model: 'llama3.2' } } } } as any)).toEqual({
            api: { model: 'llama3.2', providers: { ollama: { model: 'llama3.2' } } },
        } as any);
    });
});
