import { TestBed } from '@angular/core/testing';
import { HTTP_INTERCEPTORS, HttpClient, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { of } from 'rxjs';
import { AuthInterceptor } from './auth.interceptor';
import { AuthService } from '../services/auth.service';

describe('AuthInterceptor: an expired access token', () => {
    let http: HttpClient;
    let backend: HttpTestingController;
    let auth: any;

    beforeEach(() => {
        auth = {
            token: 'old-access',
            getAccessToken: () => auth.token,
            refresh$: jasmine.createSpy('refresh$').and.callFake(() => {
                auth.token = 'new-access';
                return of({ access_token: 'new-access' });
            }),
            clearSession: jasmine.createSpy('clearSession'),
            exitAnonymousMode: jasmine.createSpy('exitAnonymousMode'),
        };
        TestBed.configureTestingModule({
            providers: [
                provideHttpClient(withInterceptorsFromDi()),
                provideHttpClientTesting(),
                { provide: HTTP_INTERCEPTORS, useClass: AuthInterceptor, multi: true },
                { provide: AuthService, useValue: auth },
                { provide: Router, useValue: { navigateByUrl: () => Promise.resolve(true) } },
            ],
        });
        http = TestBed.inject(HttpClient);
        backend = TestBed.inject(HttpTestingController);
    });

    afterEach(() => backend.verify());

    for (const url of ['/api/auth/ws-ticket', '/api/auth/me/settings', '/api/config/']) {
        it(`is renewed quietly and the request to ${url} is retried`, () => {
            let answer: unknown;
            http.post(url, {}).subscribe((value) => (answer = value));

            backend.expectOne(url).flush({ detail: 'Token expired' }, { status: 401, statusText: 'Unauthorized' });
            const retried = backend.expectOne(url);
            expect(retried.request.headers.get('Authorization')).toBe('Bearer new-access');
            retried.flush({ ok: true });

            expect(answer).toEqual({ ok: true });
            expect(auth.refresh$).toHaveBeenCalledTimes(1);
            expect(auth.clearSession).not.toHaveBeenCalled();
        });
    }

    for (const url of ['/api/auth/ws-ticket', '/api/auth/me']) {
        it(`signs out when the sign-in has ended and ${url} refuses`, () => {
            auth.refresh$.and.returnValue(of(null));
            http.post(url, {}).subscribe({ error: () => undefined });

            backend.expectOne(url).flush({ detail: 'User not found or inactive' }, { status: 401, statusText: 'Unauthorized' });

            expect(auth.refresh$).toHaveBeenCalledTimes(1);
            expect(auth.clearSession).toHaveBeenCalled();
        });
    }

    it('does not treat wrong credentials at sign-in as an expired token', () => {
        http.post('/api/auth/login', {}).subscribe({ error: () => undefined });

        backend.expectOne('/api/auth/login').flush({ detail: 'Invalid credentials' }, { status: 401, statusText: 'Unauthorized' });

        expect(auth.refresh$).not.toHaveBeenCalled();
    });
});
