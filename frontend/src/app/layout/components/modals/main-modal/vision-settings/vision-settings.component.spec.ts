import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { VisionSettingsComponent } from './vision-settings.component';

describe('VisionSettingsComponent: module flag save', () => {
    let updates: any[];

    function create(): VisionSettingsComponent {
        updates = [];
        const configService: any = {
            getConfig$: () => of({
                vision: {
                    enabled: false,
                    screenCaptureEnabled: false,
                    attachmentPrompt: '',
                    generatedImagePrompt: '',
                    screenPrompt: '',
                    activeProvider: 'apple_vision',
                    visionModules: { apple_vision: { modelId: '', maxTokens: 128 } },
                },
                modules: {
                    vtubeStudio: false, whisper: true, minecraft: false, gaming: false,
                    alarm: false, discord: true, rag: true, visual: false,
                },
            }),
            updateConfig$: (body: any) => {
                updates.push(body);
                return of({});
            },
        };
        const resources: any = { getMonitorScreens$: () => of({ monitors: [] }) };
        const apiService: any = { getModelIndex$: () => of([]) };
        const modals: any = {};
        const notifications: any = { open: () => undefined };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        const component = new VisionSettingsComponent(
            new UntypedFormBuilder(), configService, resources, apiService, modals, notifications, localization, cdr,
        );
        component.ngOnInit();
        return component;
    }

    it('has nothing to save right after loading', () => {
        const component = create();

        expect(component.hasChanges()).toBe(false);
    });

    it('switching vision sends only its own module flag', () => {
        const component = create();

        component.visionForm.get('enabled')!.setValue(true);
        component.saveChanges();

        expect(updates.length).toBe(1);
        expect(updates[0].modules).toEqual({ visual: true });
    });
});
