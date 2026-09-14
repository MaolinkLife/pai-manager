import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { InitiativeSettingsComponent } from './initiative-settings.component';

describe('InitiativeSettingsComponent', () => {
    let saved: any[];

    function create(config: any): InitiativeSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => of(config),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
        };
        const notifications: any = { open: () => undefined };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        const component = new InitiativeSettingsComponent(
            new UntypedFormBuilder(), configService, notifications, localization, cdr,
        );
        component.ngOnInit();
        return component;
    }

    const stored = { enabled: false, chat: { enabled: true }, selfie: { enabled: true, chance: 0.4 } };

    it('shows the stored settings', () => {
        const component = create({ initiative: { ...stored, selfie: { enabled: false, chance: 0.7 } } });

        expect(component.initiativeForm.getRawValue()).toEqual({
            enabled: false,
            chat: { enabled: true },
            selfie: { enabled: false, chance: 0.7 },
        });
        expect(component.hasChanges()).toBeFalse();
    });

    it('saves only the changed field', () => {
        const component = create({ initiative: stored });

        component.initiativeForm.get('enabled')!.setValue(true);
        component.saveChanges();

        expect(saved).toEqual([{ initiative: { enabled: true } }]);
    });

    it('saves a nested change without its neighbours', () => {
        const component = create({ initiative: stored });

        component.initiativeForm.get('selfie.chance')!.setValue(0.7);
        component.saveChanges();

        expect(saved).toEqual([{ initiative: { selfie: { chance: 0.7 } } }]);
    });

    it('after a save sends only what changed since then', () => {
        const component = create({ initiative: stored });

        component.initiativeForm.get('enabled')!.setValue(true);
        component.saveChanges();
        component.initiativeForm.get('chat.enabled')!.setValue(false);
        component.saveChanges();

        expect(saved[1]).toEqual({ initiative: { chat: { enabled: false } } });
    });

    it('does not save when nothing changed', () => {
        const component = create({ initiative: stored });

        component.saveChanges();

        expect(saved).toEqual([]);
    });

    it('does not save a chance out of range', () => {
        const component = create({ initiative: stored });

        component.initiativeForm.get('selfie.chance')!.setValue(1.5);
        component.saveChanges();

        expect(saved).toEqual([]);
    });

    it('does not save when the settings could not be loaded', () => {
        const component = create(null);

        component.initiativeForm.get('enabled')!.setValue(true);
        component.saveChanges();

        expect(component.hasChanges()).toBeFalse();
        expect(saved).toEqual([]);
    });
});
