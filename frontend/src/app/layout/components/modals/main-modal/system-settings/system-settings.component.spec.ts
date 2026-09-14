import { UntypedFormBuilder } from '@angular/forms';
import { Observable, of, throwError } from 'rxjs';
import { SystemSettingsComponent } from './system-settings.component';

describe('SystemSettingsComponent password change', () => {
    let requests: any[];
    let successes: string[];
    let errors: string[];

    function create(result: Observable<any> = of({ status: 'ok', revoked_sessions: 1 })) {
        requests = [];
        successes = [];
        errors = [];
        const authService: any = {
            changePassword$: (payload: any) => {
                requests.push(payload);
                return result;
            },
        };
        const localization: any = { t: (key: string) => key };
        const notifications: any = {
            success: (message: string) => successes.push(message),
            error: (message: string) => errors.push(message),
        };
        return new SystemSettingsComponent(
            new UntypedFormBuilder(), {} as any, authService, {} as any, localization, {} as any, notifications, {} as any,
        );
    }

    function type(component: SystemSettingsComponent, current: string, next: string, repeat: string) {
        component.passwordForm.setValue({ currentPassword: current, newPassword: next, repeatPassword: repeat });
    }

    it('sends nothing while the new password is not typed the same twice', () => {
        const component = create();
        type(component, 'old-password-1', 'new-password-2', 'new-password-3');

        expect(component.passwordsDiffer()).toBeTrue();
        expect(component.canChangePassword()).toBeFalse();
        component.changePassword();

        expect(requests).toEqual([]);
    });

    it('sends nothing for a new password shorter than 8 characters', () => {
        const component = create();
        type(component, 'old-password-1', 'short', 'short');

        component.changePassword();

        expect(requests).toEqual([]);
    });

    it('changes the password and clears the fields', () => {
        const component = create();
        type(component, 'old-password-1', 'new-password-2', 'new-password-2');

        component.changePassword();

        expect(requests).toEqual([{ current_password: 'old-password-1', new_password: 'new-password-2' }]);
        expect(component.passwordForm.value).toEqual({ currentPassword: '', newPassword: '', repeatPassword: '' });
        expect(component.isPasswordBusy).toBeFalse();
        expect(successes).toEqual(['systemSettings.passwordChanged']);
    });

    it('keeps the fields and says why when the server refuses', () => {
        const component = create(throwError({ error: { detail: 'The current password is wrong' } }));
        type(component, 'wrong-password', 'new-password-2', 'new-password-2');

        component.changePassword();

        expect(component.isPasswordBusy).toBeFalse();
        expect(component.passwordForm.value.newPassword).toBe('new-password-2');
        expect(errors).toEqual(['The current password is wrong']);
    });
});

describe('SystemSettingsComponent partial saves', () => {
    let saved: any[];

    const stored = () => ({
        system: { userName: 'You', language: 'en-US', runtime: { modelMemoryProfile: 'balanced' } },
        modules: { vtubeStudio: false, whisper: true, minecraft: false, gaming: false, alarm: false, discord: false, rag: true, visual: true },
        communication: { priority: ['main_chat', 'telegram'] },
        connector: {
            tunneling: {
                enabled: false,
                provider: 'cloudflared',
                localUrl: 'http://127.0.0.1:3880',
                localPort: 3880,
                commandPath: '',
                publicUrl: '',
            },
        },
    });

    function create(config: any = stored()): SystemSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => of(config),
            getSystem$: () => of({ system: { prompt: 'A prompt', active_character_id: 'c1', char_name: 'Test' } }),
            getSystemCharacters$: () => of({ characters: [{ id: 'c1', name: 'Test', prompt: 'A prompt' }], active_character_id: 'c1' }),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
            updateSystem$: () => of({}),
        };
        const authService: any = {
            me$: () => of({ role: 'owner', settings: { language: 'en-US' } }),
            updateMeSettings$: () => of(null),
        };
        const themeService: any = { getTheme: () => 'dark', setTheme: () => undefined };
        const localization: any = { init: () => undefined, t: (key: string) => key, setLanguage: () => undefined };
        const tunnelService: any = {
            getStatus$: () => of({ running: false, public_url: '', config: { local_url: 'http://127.0.0.1:3880', local_port: 3880 } }),
        };
        const notifications: any = { success: () => undefined, error: () => undefined };
        const component = new SystemSettingsComponent(
            new UntypedFormBuilder(), configService, authService, themeService, localization, tunnelService, notifications, {} as any,
        );
        component.ngOnInit();
        return component;
    }

    it('has nothing to save right after loading', () => {
        const component = create();

        expect(component.hasChanges()).toBeFalse();
    });

    it('saves one tunnel field without the rest of the tunnel settings', () => {
        const component = create();

        component.systemForm.get('connector.tunneling.enabled')!.setValue(true);
        component.saveChanges();

        expect(saved).toEqual([{ connector: { tunneling: { enabled: true } } }]);
    });

    it('switching VTube Studio sends only that module flag', () => {
        const component = create();

        component.systemForm.get('modules.vtube_studio')!.setValue(true);
        component.saveChanges();

        expect(saved).toEqual([{ modules: { vtubeStudio: true } }]);
    });

    it('saves one log retention value alone', () => {
        const component = create();

        component.systemForm.get('auditRetention.ageInfo')!.setValue(10);
        component.saveChanges();

        expect(saved).toEqual([{ auditLogs: { retention: { ageDays: { info: 10 } } } }]);
    });

    it('shows the stored log retention instead of the form defaults', () => {
        const component = create({
            ...stored(),
            auditLogs: {
                retention: {
                    enabled: false,
                    ageDays: { debug: 7, info: 21, success: 7, warning: 30, error: 90, audit_fail: 90 },
                    hardCap: { info: 50000, success: 50000, warning: 10000, error: 1000, audit_fail: 5000 },
                },
            },
        });

        expect(component.systemForm.get('auditRetention')!.value).toEqual(jasmine.objectContaining({
            enabled: false,
            ageInfo: 21,
            ageSuccess: 7,
            capError: 1000,
        }));
        expect(component.hasChanges()).toBeFalse();
    });

    it('does not send a request when nothing changed', () => {
        const component = create();

        component.saveChanges();

        expect(saved).toEqual([]);
    });
});
