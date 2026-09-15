import { TestBed } from '@angular/core/testing';
import { BehaviorSubject, of } from 'rxjs';
import { AppComponent } from './app.component';

describe('AppComponent: the chat socket follows who is signed in', () => {
    function create() {
        const user$ = new BehaviorSubject<any>({ uuid: 'owner-uuid' });
        const auth: any = {
            token: 'access-1' as string | null,
            anonymous: false,
            currentUser$: user$,
            getAccessToken: () => auth.token,
            isAnonymousMode: () => auth.anonymous,
            isAuthenticated: () => !!auth.token,
            getCurrentUser: () => user$.value,
            bootstrapSession$: () => of(user$.value),
        };
        const socket: any = {
            connect: jasmine.createSpy('connect'),
            reconnect: jasmine.createSpy('reconnect'),
            disconnect: jasmine.createSpy('disconnect'),
        };
        const localization: any = { init: () => undefined };
        const component = TestBed.runInInjectionContext(() => new AppComponent(socket, localization, auth));
        component.ngOnInit();
        socket.connect.calls.reset();
        socket.reconnect.calls.reset();
        socket.disconnect.calls.reset();
        return { auth, socket, user$ };
    }

    it('does not reconnect when only the access token was renewed', () => {
        const { auth, socket, user$ } = create();

        auth.token = 'access-2';
        user$.next({ uuid: 'owner-uuid' });

        expect(socket.reconnect).not.toHaveBeenCalled();
        expect(socket.disconnect).not.toHaveBeenCalled();
    });

    it('reconnects when another user signs in', () => {
        const { auth, socket, user$ } = create();

        auth.token = 'access-other';
        user$.next({ uuid: 'other-uuid' });

        expect(socket.reconnect).toHaveBeenCalledTimes(1);
    });

    it('disconnects on sign-out', () => {
        const { auth, socket, user$ } = create();

        auth.token = null;
        user$.next(null);

        expect(socket.disconnect).toHaveBeenCalledTimes(1);
    });

    it('reconnects when the page switches to the anonymous guest mode', () => {
        const { auth, socket, user$ } = create();

        auth.token = null;
        auth.anonymous = true;
        user$.next(null);

        expect(socket.reconnect).toHaveBeenCalledTimes(1);
    });
});
