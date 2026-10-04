import { HttpErrorResponse, provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { AuthService, describeBootstrapError } from './auth.service';

describe('AuthService: sign-in state from the server', () => {
    let service: AuthService;
    let http: HttpTestingController;

    beforeEach(() => {
        localStorage.clear();
        TestBed.configureTestingModule({
            providers: [provideHttpClient(), provideHttpClientTesting()],
        });
        service = TestBed.inject(AuthService);
        http = TestBed.inject(HttpTestingController);
    });

    afterEach(() => {
        http.verify();
        localStorage.clear();
    });

    it('does not turn a refusal into «no owner, create one»', () => {
        let answer: unknown = 'not answered';
        service.getBootstrapState$(true).subscribe((state) => (answer = state));

        http.expectOne((request) => request.url.endsWith('/auth/bootstrap-state')).flush(
            { detail: 'API access denied by access guard policy.' },
            { status: 403, statusText: 'Forbidden' },
        );

        expect(answer).toBeNull();
        expect(service.bootstrapError?.status).toBe(403);
        expect(service.bootstrapError?.message).toContain('API access denied by access guard policy.');
        expect(localStorage.getItem('chat_ai_auth_bootstrap_state')).toBeNull();
    });

    it('keeps the answer and clears an earlier error when the server answers', () => {
        service.bootstrapError = { status: 0, message: 'old' };
        let answer: any = null;
        service.getBootstrapState$(true).subscribe((state) => (answer = state));

        http.expectOne((request) => request.url.endsWith('/auth/bootstrap-state')).flush({
            has_owner: true,
            requires_setup: false,
            auth_users_count: 1,
            first_registration_role: 'user',
            allow_anonymous: true,
        });

        expect(answer?.has_owner).toBe(true);
        expect(service.bootstrapError).toBeNull();
    });

    it('describes a silent server and a server error', () => {
        expect(describeBootstrapError(new HttpErrorResponse({ status: 0 })).message).toContain('не отвечает');
        expect(describeBootstrapError(new HttpErrorResponse({ status: 500 })).message).toContain('500');
    });

    it('treats only a signed-in owner as the owner', () => {
        expect(service.isOwner()).toBe(false);

        localStorage.setItem('chat_ai_user', JSON.stringify({ uuid: 'u', name: 'U', role: 'user' }));
        expect(new AuthService(null as any).isOwner()).toBe(false);

        localStorage.setItem('chat_ai_user', JSON.stringify({ uuid: 'o', name: 'O', role: 'owner' }));
        const owner = new AuthService(null as any);
        expect(owner.isOwner()).toBe(true);

        owner.enterAnonymousMode();
        expect(owner.isOwner()).toBe(false);
    });
});
