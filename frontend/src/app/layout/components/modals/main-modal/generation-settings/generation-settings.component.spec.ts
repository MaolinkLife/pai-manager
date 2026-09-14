import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { GenerationSettingsComponent } from './generation-settings.component';

describe('GenerationSettingsComponent: partial saves', () => {
    let saved: any[];

    const stored = () => ({
        api: {
            type: 'ollama',
            streaming: true,
            model: 'qwen3.5:9b',
            tokenLimit: 4096,
            messagePairLimit: 4,
            activeProvider: 'ollama',
            fallbackOrder: [],
            providers: {
                ollama: { model: 'qwen3.5:9b', temperature: 0.7, maxTokens: 4096, baseUrl: 'http://localhost:11434' },
            },
        },
        generateSettings: {
            name: 'Default',
            description: 'Basic generation parameters',
            temperature: 0.85,
            topP: 0.9,
            topK: 50,
            minP: 0.05,
            repeatPenalty: 1.2,
            numPredict: 2048,
            normalizeMessages: false,
            stop: null,
        },
    });

    function create(config: any = stored()): GenerationSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => of(config),
            getGenerationPresets$: () => of([]),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
        };
        const apiService: any = { getModelIndex$: () => of([]) };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const notifications: any = { open: () => undefined };
        const component = new GenerationSettingsComponent(
            new UntypedFormBuilder(), configService, apiService, localization, notifications,
        );
        component.ngOnInit();
        return component;
    }

    it('has nothing to save right after loading', () => {
        const component = create();

        expect(component.hasChanges()).toBeFalse();
    });

    it('saves one generation parameter alone', () => {
        const component = create();

        component.generationSettingsForm.get('temperature')!.setValue(1.1);
        component.saveChanges();

        expect(saved).toEqual([{ generateSettings: { temperature: 1.1 } }]);
    });

    it('saves a model change without the untouched provider settings', () => {
        const component = create();

        component.selectModel('llama3.2');
        component.saveChanges();

        expect(saved).toEqual([{ api: { model: 'llama3.2', providers: { ollama: { model: 'llama3.2' } } } }]);
    });

    it('after a save sends only what changed since then', () => {
        const component = create();

        component.generationSettingsForm.get('temperature')!.setValue(1.1);
        component.saveChanges();
        component.generationSettingsForm.get('topK')!.setValue(40);
        component.saveChanges();

        expect(saved[1]).toEqual({ generateSettings: { topK: 40 } });
    });

    it('does not save when the settings could not be loaded', () => {
        const component = create(null);

        component.generationSettingsForm.get('temperature')!.setValue(1.1);
        component.saveChanges();

        expect(saved).toEqual([]);
    });
});
