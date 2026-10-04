import { mapMemoryDtoToModel, mapMemoryModelToDto } from './memory-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';
import { MemoryConfig, ProjectConfig } from '../models/project-config.model';

const partialSave = (memory: unknown) =>
    mapPartialModelToDto({ memory } as Partial<ProjectConfig>).memory as unknown;

describe('memory settings save: only the changed fields go to the server', () => {
    it('sends the memory sections of the RAG tab without the base memory fields', () => {
        const dto = partialSave({
            consolidation: {
                importanceThreshold: 0.3,
                judge: { enabled: true, provider: 'ollama', model: 'judge:3b', temperature: 0, maxTokens: 512, requestTimeout: 60, systemPrompt: '' },
            },
            shortTerm: { summarySystemPrompt: 'summarize', summaryTaskPrompt: '' },
            diary: { narrative: { enabled: true, minChars: 80, maxChars: 3000 }, systemPrompt: 'diary', userTemplate: '' },
        }) as Record<string, unknown>;

        ['deep_memory_enabled', 'recent_limit', 'similarity_threshold', 'session_window', 'session_enabled', 'embedding_provider', 'embedding_model']
            .forEach((key) => expect(key in dto, key).toBe(false));
        expect(dto).toEqual({
            consolidation: {
                importance_threshold: 0.3,
                judge: { enabled: true, provider: 'ollama', model: 'judge:3b', temperature: 0, max_tokens: 512, request_timeout: 60, system_prompt: '' },
            },
            short_term: { summary_system_prompt: 'summarize', summary_task_prompt: '' },
            diary: { narrative: { enabled: true, min_chars: 80, max_chars: 3000 }, system_prompt: 'diary', user_template: '' },
        });
    });

    it('sends a single changed field alone', () => {
        expect(partialSave({ recentLimit: 48 })).toEqual({ recent_limit: 48 });
        expect(partialSave({ shortTerm: { startupRefreshEnabled: true } })).toEqual({ short_term: { startup_refresh_enabled: true } });
        expect(partialSave({ diary: { narrative: { enabled: false } } })).toEqual({ diary: { narrative: { enabled: false } } });
    });
});

describe('memory config mapper: technical prompts', () => {
    const fromServer = mapMemoryDtoToModel({
        recent_limit: 32,
        similarity_threshold: 0.7,
        session_window: 'day',
        session_enabled: true,
        embedding_provider: 'auto',
        embedding_model: 'nomic-embed-text',
        consolidation: { importance_threshold: 0.2, judge: { system_prompt: 'judge' } },
        short_term: { summary_system_prompt: 'summarize', summary_task_prompt: 'what stayed' },
        diary: { narrative: {}, system_prompt: 'diary in {language}', user_template: '{day} {transcript}' },
    });

    it('carries the prompts from the server into the form', () => {
        expect(fromServer.consolidation?.judge.systemPrompt).toBe('judge');
        expect(fromServer.shortTerm).toEqual({
            startupRefreshEnabled: false,
            summarySystemPrompt: 'summarize',
            summaryTaskPrompt: 'what stayed',
        });
        expect(fromServer.diary?.systemPrompt).toBe('diary in {language}');
        expect(fromServer.diary?.userTemplate).toBe('{day} {transcript}');
    });

    it('sends the prompts back as the server names them', () => {
        const dto = mapMemoryModelToDto(fromServer);

        expect(dto.consolidation?.judge?.system_prompt).toBe('judge');
        expect(dto.short_term).toEqual({
            startup_refresh_enabled: false,
            summary_system_prompt: 'summarize',
            summary_task_prompt: 'what stayed',
        });
        expect(dto.diary?.system_prompt).toBe('diary in {language}');
        expect(dto.diary?.user_template).toBe('{day} {transcript}');
    });

    it('does not wipe prompts a save never loaded', () => {
        const partial = {
            diary: { narrative: { enabled: true, minChars: 80, maxChars: 3000 } },
        } as MemoryConfig;

        const dto = mapMemoryModelToDto(partial);

        expect('system_prompt' in (dto.diary ?? {})).toBe(false);
        expect('user_template' in (dto.diary ?? {})).toBe(false);
        expect(dto.short_term).toBeUndefined();
    });
});
