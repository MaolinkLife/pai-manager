import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { environment } from '../../../environments/environment';
import { AuthService } from './auth.service';

describe('AuthService: renewing the session', () => {
    const keys = ['chat_ai_access_token', 'chat_ai_refresh_token', 'chat_ai_user'];
    const refreshUrl = `${environment.apiBaseUrl}/auth/refresh`;
    let service: AuthService;
    let backend: HttpTestingController;

    beforeEach(() => {
        localStorage.setItem('chat_ai_access_token', 'access-1');
        localStorage.setItem('chat_ai_refresh_token', 'refresh-1');
        localStorage.setItem(
            'chat_ai_user',
            JSON.stringify({ uuid: 'owner-uuid', name: 'Owner', role: 'owner', trust_level: 1, is_active: true }),
        );
        TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
        service = TestBed.inject(AuthService);
        backend = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        backend.verify();
        keys.forEach((key) => localStorage.removeItem(key));
    });

    it('keeps the session another tab has just renewed instead of signing out', () => {
        let renewed: any;
        service.refresh$().subscribe((value) => (renewed = value));

        // Another tab renewed first: this tab's refresh token is spent, the new pair is stored.
        localStorage.setItem('chat_ai_access_token', 'access-2');
        localStorage.setItem('chat_ai_refresh_token', 'refresh-2');
        backend.expectOne(refreshUrl).flush({ detail: 'Refresh token is revoked' }, { status: 401, statusText: 'Unauthorized' });

        expect(renewed?.access_token).toBe('access-2');
        expect(service.getAccessToken()).toBe('access-2');
        expect(service.getRefreshToken()).toBe('refresh-2');
    });

    it('signs out when the refresh token is refused and no other tab renewed it', () => {
        let renewed: any = 'untouched';
        service.refresh$().subscribe((value) => (renewed = value));

        backend.expectOne(refreshUrl).flush({ detail: 'Refresh token is revoked' }, { status: 401, statusText: 'Unauthorized' });

        expect(renewed).toBeNull();
        expect(service.getAccessToken()).toBeNull();
        expect(service.getRefreshToken()).toBeNull();
    });
});
