import { UntypedFormBuilder } from '@angular/forms';
import { of, throwError } from 'rxjs';
import { ComplianceSettingsComponent } from './compliance-settings.component';

describe('ComplianceSettingsComponent', () => {
    let saved: any[];

    function create(config$: any): ComplianceSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => config$,
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
        };
        const notifications: any = { open: () => undefined };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        const component = new ComplianceSettingsComponent(
            new UntypedFormBuilder(), configService, notifications, localization, cdr,
        );
        component.ngOnInit();
        return component;
    }

    const stored = {
        validator: { enabled: true, threshold: 0.8, maxTokens: 300, temperature: 0.1, instructionCharLimit: 5000, outputCharLimit: 5000, systemPrompt: 'judge' },
        languageGuard: { enabled: true, minDominance: 0.6, minOutputChars: 50 },
        confidence: { enabled: true, threshold: 0.4, maxTokens: 80, temperature: 0.2, userCharLimit: 1500, outputCharLimit: 3000, systemPrompt: '' },
        factuality: { enabled: false, gateOnLowConfidence: false, topK: 5, minSimilarity: 0.5, maxClaims: 8, claimMinLength: 4 },
        selfWatcher: { enabled: true, mismatchThreshold: 0.3, nightlyReflectionEnabled: false, lookbackDays: 14, maxEventsInCluster: 30, llmMaxTokens: 200, llmTemperature: 0.4, reflectionPrompt: '' },
    };

    it('saves only the changed field', () => {
        const component = create(of(stored));

        component.complianceForm.get('validator.threshold')!.setValue(0.9);
        component.saveChanges();

        expect(saved).toEqual([{ validator: { threshold: 0.9 } }]);
    });

    it('saves changes in two sections without their neighbours', () => {
        const component = create(of(stored));

        component.complianceForm.get('languageGuard.enabled')!.setValue(false);
        component.complianceForm.get('selfWatcher.lookbackDays')!.setValue(30);
        component.saveChanges();

        expect(saved).toEqual([{ languageGuard: { enabled: false }, selfWatcher: { lookbackDays: 30 } }]);
    });

    it('after a save sends only what changed since then', () => {
        const component = create(of(stored));

        component.complianceForm.get('validator.threshold')!.setValue(0.9);
        component.saveChanges();
        component.complianceForm.get('factuality.topK')!.setValue(7);
        component.saveChanges();

        expect(saved[1]).toEqual({ factuality: { topK: 7 } });
    });

    it('does not save when nothing changed', () => {
        const component = create(of(stored));

        component.saveChanges();

        expect(saved).toEqual([]);
    });

    it('does not save when the settings could not be loaded', () => {
        const component = create(throwError(() => new Error('offline')));

        component.complianceForm.get('validator.enabled')!.setValue(true);
        component.saveChanges();

        expect(component.hasChanges()).toBeFalse();
        expect(saved).toEqual([]);
    });
});
