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
            innerVoice: { enabled: true, maxTokens: 80, temperature: 0.7, language: '', systemPrompt: '' },
        },
    });

    function create(config$: Observable<any> = of(stored())): MoralSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => config$,
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
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

        expect(component.hasChanges()).toBeFalse();
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

    it('does not save when the settings could not be loaded', () => {
        const component = create(throwError(() => new Error('offline')));

        component.moralForm.get('decay.globalRate')!.setValue(0.1);
        component.saveChanges();

        expect(component.hasChanges()).toBeFalse();
        expect(saved).toEqual([]);
    });
});
