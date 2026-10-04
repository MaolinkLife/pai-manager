import { UntypedFormBuilder } from '@angular/forms';
import { Observable, of, throwError } from 'rxjs';
import { MoralSettingsComponent } from './moral-settings.component';

describe('MoralSettingsComponent: partial saves', () => {
    let saved: any[];

    const stored = () => ({
        moral: {
            enabled: true,
            activeProvider: 'ollama',
            fallbackOrder: ['heuristic'],
            releaseAfterUse: true,
            systemPrompt: 'Matrix prompt.',
            providers: { ollama: { model: 'qwen3.5:9b', temperature: 0.6, maxTokens: 512, thinking: false } },
            decay: { enabled: true, globalRate: 0.05 },
            forgiveness: { enabled: true, compensatingTones: ['warm'], softenableEmotions: ['anger'], deltaPerEvent: 0.1, lookbackDays: 14 },
            scars: {
                enabled: false,
                triggers: [{ name: 'insult', intents: ['insult'], tones: [], keywords: [], persistenceFloor: 0.4, intensityBoost: 0.2 }],
            },
            innerVoice: { enabled: true, maxTokens: 80, temperature: 0.7, undercurrentThreshold: 0.5, language: '', systemPrompt: '' },
        },
    });

    let defaultsAsked: string[];

    function create(
        config$: Observable<any> = of(stored()),
        defaults: Record<string, any> | null = { 'moral.system_prompt': 'Built-in matrix prompt.' },
    ): MoralSettingsComponent {
        saved = [];
        defaultsAsked = [];
        const configService: any = {
            getConfig$: () => config$,
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
            getDefaultValue$: (path: string) => {
                defaultsAsked.push(path);
                return of(defaults ? defaults[path] ?? null : null);
            },
        };
        const apiService: any = { getModelIndex$: () => of([]) };
        const notifications: any = { open: () => undefined };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        const component = new MoralSettingsComponent(
            new UntypedFormBuilder(), apiService, configService, notifications, localization, cdr,
        );
        component.ngOnInit();
        return component;
    }

    it('has nothing to save right after loading', () => {
        const component = create();

        expect(component.hasChanges()).toBe(false);
    });

    it('saves one decay value alone', () => {
        const component = create();

        component.moralForm.get('decay.globalRate')!.setValue(0.1);
        component.saveChanges();

        expect(saved).toEqual([{ moral: { decay: { globalRate: 0.1 } } }]);
    });

    it('switching scars sends the switch without the trigger list', () => {
        const component = create();

        component.moralForm.get('scars.enabled')!.setValue(true);
        component.saveChanges();

        expect(saved).toEqual([{ moral: { scars: { enabled: true } } }]);
    });

    it('shows the stored undercurrent threshold and saves a change of it alone', () => {
        const component = create();

        expect(component.moralForm.get('innerVoice.undercurrentThreshold')!.value).toBe(0.5);
        component.moralForm.get('innerVoice.undercurrentThreshold')!.setValue(0.6);
        component.saveChanges();

        expect(saved).toEqual([{ moral: { innerVoice: { undercurrentThreshold: 0.6 } } }]);
    });

    it('shows the stored desire threshold and saves a change of it alone', () => {
        const component = create();

        expect(component.moralForm.get('innerVoice.desireThreshold')!.value).toBe(0.6);
        component.moralForm.get('innerVoice.desireThreshold')!.setValue(0.7);
        component.saveChanges();

        expect(saved).toEqual([{ moral: { innerVoice: { desireThreshold: 0.7 } } }]);
    });

    it('shows the stored matrix prompt as it is', () => {
        const component = create();

        expect(component.moralForm.get('systemPrompt')!.value).toBe('Matrix prompt.');
        expect(defaultsAsked).toEqual([]);
    });

    it('shows the built-in matrix prompt from the server when none is stored, with nothing to save', () => {
        const withoutPrompt = stored();
        withoutPrompt.moral.systemPrompt = '';
        const component = create(of(withoutPrompt));

        expect(defaultsAsked).toEqual(['moral.system_prompt']);
        expect(component.moralForm.get('systemPrompt')!.value).toBe('Built-in matrix prompt.');
        expect(component.hasChanges()).toBe(false);
    });

    it('never puts a prompt of its own into the field', () => {
        const withoutPrompt = stored();
        withoutPrompt.moral.systemPrompt = '';
        const component = create(of(withoutPrompt), null);

        expect(component.moralForm.get('systemPrompt')!.value).toBe('');
        component.moralForm.get('decay.globalRate')!.setValue(0.1);
        component.saveChanges();

        expect(saved).toEqual([{ moral: { decay: { globalRate: 0.1 } } }]);
    });

    it('does not save when the settings could not be loaded', () => {
        const component = create(throwError(() => new Error('offline')));

        component.moralForm.get('decay.globalRate')!.setValue(0.1);
        component.saveChanges();

        expect(component.hasChanges()).toBe(false);
        expect(saved).toEqual([]);
    });
});
