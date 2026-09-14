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
