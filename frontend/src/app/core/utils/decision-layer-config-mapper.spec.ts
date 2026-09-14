import { mapDecisionLayerDtoToModel, mapDecisionLayerModelToDto } from './decision-layer-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';
import { ProjectConfig } from '../models/project-config.model';

const partialSave = (decisionLayer: unknown) =>
    mapPartialModelToDto({ decisionLayer } as Partial<ProjectConfig>).decision_layer as unknown;

describe('decision layer config mapper: orchestrator prompt', () => {
    it('carries the prompt from the server into the form and back', () => {
        const model = mapDecisionLayerDtoToModel({ orchestrator_prompt: 'route it' });

        expect(model.orchestratorPrompt).toBe('route it');
        expect(mapDecisionLayerModelToDto(model).orchestrator_prompt).toBe('route it');
    });

    it('does not wipe the prompt when a save changes something else', () => {
        const dto = mapDecisionLayerModelToDto({ maxSteps: 6 });

        expect('orchestrator_prompt' in dto).toBeFalse();
    });
});

describe('decision layer settings save: only the changed fields go to the server', () => {
    it('sends only the instructor schema when only the schema changed', () => {
        expect(partialSave({ instructor: { buildSchema: '[CORE]\n{core}' } })).toEqual({
            instructor: { build_schema: '[CORE]\n{core}' },
        });
    });

    it('sends the mode and the model the owner changed, and nothing else', () => {
        expect(partialSave({ mode: 'llm', providers: { ollama: { model: 'router:7b' } } })).toEqual({
            mode: 'llm',
            providers: { ollama: { model: 'router:7b' } },
        });
    });

    it('sends max tokens without the other provider fields', () => {
        expect(partialSave({ providers: { ollama: { maxTokens: 256 } } })).toEqual({
            providers: { ollama: { max_tokens: 256 } },
        });
    });

    it('carries no capabilities: they come from the model index', () => {
        const dto = mapDecisionLayerModelToDto({ maxSteps: 6 }) as unknown as Record<string, unknown>;

        expect('capabilities' in dto).toBeFalse();
    });

    it('sends the orchestrator prompt alone when only it changed', () => {
        expect(partialSave({ orchestratorPrompt: 'route strictly' })).toEqual({
            orchestrator_prompt: 'route strictly',
        });
    });
});
