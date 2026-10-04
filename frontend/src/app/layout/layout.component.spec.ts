import { of } from 'rxjs';
import { LayoutComponent } from './layout.component';

describe('LayoutComponent: quick generation panel saves', () => {
    let saved: any[];

    function create(): any {
        saved = [];
        const component: any = Object.create(LayoutComponent.prototype);
        Object.assign(component, {
            generationPanelSaving: false,
            generationConfigSnapshot: {
                api: {
                    type: 'ollama',
                    streaming: true,
                    model: 'qwen3.5:9b',
                    tokenLimit: 4096,
                    messagePairLimit: 4,
                    activeProvider: 'ollama',
                    fallbackOrder: [],
                    providers: {
                        ollama: { model: 'qwen3.5:9b', temperature: 0.85, maxTokens: 2048, baseUrl: 'http://localhost:11434' },
                    },
                },
                generateSettings: {
                    name: 'Default',
                    temperature: 0.85,
                    topP: 0.9,
                    topK: 50,
                    minP: 0.05,
                    repeatPenalty: 1.2,
                    numPredict: 2048,
                    normalizeMessages: false,
                    stop: null,
                },
            },
            generationProvider: 'ollama',
            generationModel: 'qwen3.5:9b',
            generationTemperature: 0.85,
            generationTopP: 0.9,
            generationTopK: 50,
            generationMaxTokens: 2048,
            showAllChatSources: false,
            configService: {
                updateConfig$: (payload: any) => {
                    saved.push(payload);
                    return of({});
                },
            },
            notificationService: { open: () => undefined },
        });
        return component;
    }

    it('saves a model change without the untouched settings', () => {
        const component = create();

        component.generationModel = 'llama3.2';
        component.saveQuickGenerationSettings();

        expect(saved).toEqual([{ api: { model: 'llama3.2', providers: { ollama: { model: 'llama3.2' } } } }]);
    });

    it('a temperature change reaches the provider and the generation settings, nothing else', () => {
        const component = create();

        component.generationTemperature = 1.0;
        component.saveQuickGenerationSettings();

        expect(saved).toEqual([{
            api: { providers: { ollama: { temperature: 1.0 } } },
            generateSettings: { temperature: 1.0 },
        }]);
    });

    it('after a save sends only what changed since then', () => {
        const component = create();

        component.generationTopK = 40;
        component.saveQuickGenerationSettings();
        component.generationTopP = 0.8;
        component.saveQuickGenerationSettings();

        expect(saved[1]).toEqual({ generateSettings: { topP: 0.8 } });
    });

    it('sends no request when nothing changed', () => {
        const component = create();

        component.saveQuickGenerationSettings();

        expect(saved).toEqual([]);
        expect(component.generationPanelSaving).toBe(false);
    });
});
