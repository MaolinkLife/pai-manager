import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { ConnectionsSettingsComponent } from './connections-settings.component';

describe('ConnectionsSettingsComponent: partial saves', () => {
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
                ollama: { model: 'qwen3.5:9b', baseUrl: 'http://localhost:11434', temperature: 0.7, maxTokens: 4096 },
                openrouter: { model: '', baseUrl: 'https://openrouter.ai/api/v1', apiKey: '' },
            },
        },
    });

    function create(): ConnectionsSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => of(stored()),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
        };
        const notifications: any = { open: () => undefined };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        const component = new ConnectionsSettingsComponent(
            new UntypedFormBuilder(), configService, notifications, localization, cdr,
        );
        component.ngOnInit();
        return component;
    }

    it('saves only the changed field, without defaults for providers the config does not have', () => {
        const component = create();

        component.form.get('ollama.baseUrl')!.setValue('http://10.0.0.2:11434');
        component.saveChanges();

        expect(saved).toEqual([{ api: { providers: { ollama: { baseUrl: 'http://10.0.0.2:11434' } } } }]);
    });

    it('switching the provider carries its model along', () => {
        const component = create();

        component.form.get('openrouter.model')!.setValue('gpt-mini');
        component.form.get('activeProvider')!.setValue('openrouter');
        component.saveChanges();

        expect(saved).toEqual([{
            api: { activeProvider: 'openrouter', model: 'gpt-mini', providers: { openrouter: { model: 'gpt-mini' } } },
        }]);
    });

    it('after a save sends only what changed since then', () => {
        const component = create();

        component.form.get('ollama.baseUrl')!.setValue('http://10.0.0.2:11434');
        component.saveChanges();
        component.form.get('openrouter.apiKey')!.setValue('key');
        component.saveChanges();

        expect(saved[1]).toEqual({ api: { providers: { openrouter: { apiKey: 'key' } } } });
    });

    it('does not save when nothing changed', () => {
        const component = create();

        component.saveChanges();

        expect(saved).toEqual([]);
    });
});
