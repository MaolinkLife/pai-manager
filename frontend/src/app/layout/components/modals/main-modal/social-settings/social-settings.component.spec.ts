import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { SocialSettingsComponent } from './social-settings.component';

describe('SocialSettingsComponent: partial saves', () => {
    let saved: any[];

    const stored = () => ({
        modules: { discord: false, whisper: true },
        communication: { priority: ['main_chat', 'telegram'] },
        telegram: {
            enabled: false,
            mode: 'mtproto',
            api_id: 12345,
            api_hash: 'test-hash',
            session_name: 'test_session',
            queue_size: 256,
            channels: { reflection_instruction: 'Reflect briefly.' },
            reflection: { prompt: 'Write a short reflection.' },
            initiative: { prompt_template: 'Say hello after {idle_minutes} minutes.' },
            autonomous_inbox: { prompt_template: 'Pick one action.' },
        },
    });

    function create(): SocialSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => of(stored()),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
        };
        // Only the status the tab reads on load; any other Telegram call fails the test instead of reaching a network.
        const telegramService: any = { getStatus$: () => of({ telegram: null }) };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const notifications: any = { success: () => undefined, error: () => undefined };
        const cdr: any = { detectChanges: () => undefined, markForCheck: () => undefined };
        const zone: any = { run: (work: () => void) => work() };
        const component = new SocialSettingsComponent(
            new UntypedFormBuilder(), configService, telegramService, localization, notifications, cdr, zone,
        );
        component.ngOnInit();
        return component;
    }

    it('has nothing to save right after loading', () => {
        const component = create();

        expect(component.hasChanges()).toBeFalse();
    });

    it('saves one Telegram field without the credentials and the rest of the bridge settings', () => {
        const component = create();

        component.socialForm.get('telegram.queue_size')!.setValue(512);
        component.saveChanges();

        expect(saved).toEqual([{ telegram: { queue_size: 512 } }]);
    });

    it('switching Discord sends only that flag', () => {
        const component = create();

        component.socialForm.get('modules.discord')!.setValue(true);
        component.saveChanges();

        expect(saved).toEqual([{ modules: { discord: true } }]);
    });

    it('changing the primary channel sends only the priority', () => {
        const component = create();

        component.socialForm.get('communication.primary_channel')!.setValue('telegram');
        component.saveChanges();

        expect(saved).toEqual([{ communication: { priority: ['telegram', 'main_chat'] } }]);
    });

    it('does not send a request when nothing changed', () => {
        const component = create();

        component.saveChanges();

        expect(saved).toEqual([]);
    });
});
