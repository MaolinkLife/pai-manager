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

        expect(component.passwordsDiffer()).toBe(true);
        expect(component.canChangePassword()).toBe(false);
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
        expect(component.isPasswordBusy).toBe(false);
        expect(successes).toEqual(['systemSettings.passwordChanged']);
    });

    it('keeps the fields and says why when the server refuses', () => {
        const component = create(throwError({ error: { detail: 'The current password is wrong' } }));
        type(component, 'wrong-password', 'new-password-2', 'new-password-2');

        component.changePassword();

        expect(component.isPasswordBusy).toBe(false);
        expect(component.passwordForm.value.newPassword).toBe('new-password-2');
        expect(errors).toEqual(['The current password is wrong']);
    });
});

describe('SystemSettingsComponent devices', () => {
    let calls: string[];
    let successes: string[];
    let errors: string[];

    const devices = [
        {
            id: 'this-device',
            user_agent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36',
            ip_address: '127.0.0.1',
            last_active_at: '2031-01-01T10:00:00+00:00',
            expires_at: '2031-01-31T10:00:00+00:00',
            current: true,
        },
        {
            id: 'phone',
            user_agent: 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36',
            ip_address: '10.0.0.2',
            last_active_at: '2031-01-01T11:00:00+00:00',
            expires_at: '2031-01-31T11:00:00+00:00',
            current: false,
        },
        {
            id: 'robot',
            user_agent: null,
            ip_address: null,
            last_active_at: null,
            expires_at: '2031-01-31T12:00:00+00:00',
            current: false,
        },
    ];

    function create(options: { others?: Observable<any>; one?: Observable<any> } = {}) {
        calls = [];
        successes = [];
        errors = [];
        const authService: any = {
            listSessions$: () => {
                calls.push('list');
                return of({ sessions: devices });
            },
            revokeOtherSessions$: () => {
                calls.push('revoke-others');
                return options.others ?? of({ status: 'ok', revoked_sessions: 2 });
            },
            revokeSession$: (id: string) => {
                calls.push(`revoke:${id}`);
                return options.one ?? of({ status: 'ok' });
            },
        };
        const localization: any = {
            t: (key: string) => (key === 'systemSettings.devicesSignedOutOthers' ? 'signed out on {count}' : key),
        };
        const notifications: any = {
            success: (message: string) => successes.push(message),
            error: (message: string) => errors.push(message),
        };
        return new SystemSettingsComponent(
            new UntypedFormBuilder(), {} as any, authService, {} as any, localization, {} as any, notifications, {} as any,
        );
    }

    it('lists the devices with a readable name and marks this one', () => {
        const component = create();

        component.loadDevices();

        expect(calls).toEqual(['list']);
        expect(component.devices.map((device) => [device.id, device.label, device.ipAddress, device.current])).toEqual([
            ['this-device', 'Chrome · Windows', '127.0.0.1', true],
            ['phone', 'Chrome · Android', '10.0.0.2', false],
            ['robot', 'systemSettings.devicesUnknown', '', false],
        ]);
    });

    it('signs out one device and reloads the list', () => {
        const component = create();
        component.loadDevices();

        component.signOutDevice(component.devices[1]);

        expect(calls).toEqual(['list', 'revoke:phone', 'list']);
        expect(successes).toEqual(['systemSettings.devicesSignedOutOne']);
        expect(component.isDevicesBusy).toBe(false);
    });

    it('never signs out this device from the list', () => {
        const component = create();
        component.loadDevices();

        component.signOutDevice(component.devices[0]);

        expect(calls).toEqual(['list']);
    });

    it('signs out the other devices after confirmation and says on how many', () => {
        const component = create();
        const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);

        component.signOutOtherDevices();

        expect(confirm).toHaveBeenCalled();
        expect(calls).toEqual(['revoke-others', 'list']);
        expect(successes).toEqual(['signed out on 2']);
        expect(component.isDevicesBusy).toBe(false);
    });

    it('sends nothing when the confirmation is cancelled', () => {
        const component = create();
        vi.spyOn(window, 'confirm').mockReturnValue(false);

        component.signOutOtherDevices();

        expect(calls).toEqual([]);
        expect(successes).toEqual([]);
    });

    it('says why when the server refuses and keeps the list', () => {
        const component = create({ one: throwError({ error: { detail: 'No such signed-in device' } }) });
        component.loadDevices();

        component.signOutDevice(component.devices[1]);

        expect(calls).toEqual(['list', 'revoke:phone']);
        expect(errors).toEqual(['No such signed-in device']);
        expect(component.devices.length).toBe(3);
        expect(component.isDevicesBusy).toBe(false);
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
            listSessions$: () => of({ sessions: [] }),
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

        expect(component.hasChanges()).toBe(false);
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

        expect(component.systemForm.get('auditRetention')!.value).toEqual(expect.objectContaining({
            enabled: false,
            ageInfo: 21,
            ageSuccess: 7,
            capError: 1000,
        }));
        expect(component.hasChanges()).toBe(false);
    });

    it('falls back to the server retention defaults when the settings did not load', () => {
        const component = create(null);

        expect(component.systemForm.get('auditRetention')!.value).toEqual(expect.objectContaining({
            ageInfo: 7,
            ageSuccess: 7,
            ageWarning: 30,
            ageError: 90,
            ageAuditFail: 90,
        }));
    });

    it('shows the stored sign-in lifetimes', () => {
        const base = stored();
        const component = create({
            ...base,
            system: { ...base.system, security: { accessTokenTtlMinutes: 20, refreshTtlDays: 60 } },
        });

        expect(component.systemForm.get('security')!.value).toEqual({ accessTokenTtlMinutes: 20, refreshTtlDays: 60 });
        expect(component.hasChanges()).toBe(false);
    });

    it('falls back to fifteen minutes and thirty days when no lifetimes are stored', () => {
        const component = create();

        expect(component.systemForm.get('security')!.value).toEqual({ accessTokenTtlMinutes: 15, refreshTtlDays: 30 });
    });

    it('saves a changed sign-in lifetime alone', () => {
        const component = create();

        component.systemForm.get('security.refreshTtlDays')!.setValue(60);
        component.saveChanges();

        expect(saved).toEqual([{ system: { security: { refreshTtlDays: 60 } } }]);
    });

    it('does not send a request when nothing changed', () => {
        const component = create();

        component.saveChanges();

        expect(saved).toEqual([]);
    });
});
