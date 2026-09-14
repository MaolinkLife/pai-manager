import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { ModelIndexEntry } from '../../../../../core/services/api.service';
import { CoreSettingsComponent } from './core-settings.component';

const entry = (name: string, capabilities: string[]): ModelIndexEntry => ({
    provider: 'ollama',
    name,
    capabilities,
    declared: capabilities,
    declared_known: true,
    owner_marked: false,
    differs: false,
});

describe('CoreSettingsComponent router model capabilities', () => {
    function create(index: ModelIndexEntry[] | null) {
        const configService: any = {
            getConfig$: () => of({ decisionLayer: { mode: 'llm', providers: { ollama: { model: 'qwen3:8b' } } } }),
        };
        const apiService: any = {
            getModelIndex$: () => of(index),
        };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const notifications: any = { open: () => undefined };
        const component = new CoreSettingsComponent(new UntypedFormBuilder(), localization, configService, apiService, notifications);
        component.ngOnInit();
        return component;
    }

    it('shows what the index says the router model can do', () => {
        const component = create([entry('qwen3:8b', ['completion', 'tools']), entry('gpt-oss:20b', ['completion', 'thinking'])]);

        expect(component.routerModelEntry?.capabilities).toEqual(['completion', 'tools']);
    });

    it('follows the model the owner picks', () => {
        const component = create([entry('qwen3:8b', ['completion', 'tools']), entry('gpt-oss:20b', ['completion', 'thinking'])]);

        component.dlForm.get('providers.ollama.model')!.setValue('gpt-oss:20b');

        expect(component.routerModelEntry?.name).toBe('gpt-oss:20b');
    });

    it('offers only text models and keeps the chosen one with a note', () => {
        const component = create([entry('qwen3:8b', ['tools']), entry('gpt-oss:20b', ['completion', 'thinking'])]);

        expect(component.ollamaModelOptions).toEqual([
            {
                value: 'qwen3:8b',
                label: 'qwen3:8b — settingsPage.models.optionsNotMarked: settingsPage.models.capabilities.completion',
            },
            { value: 'gpt-oss:20b', label: 'gpt-oss:20b' },
        ]);
    });

    it('says nothing is known for a model the index does not have', () => {
        const component = create([]);

        expect(component.routerModelEntry).toBeNull();
    });

    it('keeps no capabilities of its own in the saved settings', () => {
        const component = create([]);

        expect('capabilities' in (component as any).buildDecisionLayerConfigFromForm()).toBeFalse();
    });
});
