import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable, of } from 'rxjs';
import { catchError, finalize, map, shareReplay, switchMap, tap } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import {
    AuthBootstrapState,
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthTokenResponse,
    AuthUser,
} from '../models/auth.model';

@Injectable({
    providedIn: 'root'
})
export class AuthService {
    private readonly apiUrl = `${environment.apiBaseUrl}/auth`;
    private readonly accessTokenKey = 'chat_ai_access_token';
    private readonly refreshTokenKey = 'chat_ai_refresh_token';
    private readonly userKey = 'chat_ai_user';
    private readonly anonymousModeKey = 'chat_ai_anonymous_mode';
    private readonly bootstrapStateKey = 'chat_ai_auth_bootstrap_state';

    private readonly currentUserSubject = new BehaviorSubject<AuthUser | null>(this.loadStoredUser());
    readonly currentUser$ = this.currentUserSubject.asObservable();
    private readonly bootstrapStateSubject = new BehaviorSubject<AuthBootstrapState | null>(
        this.loadStoredBootstrapState()
    );
    private refreshInFlight$: Observable<AuthTokenResponse | null> | null = null;

    constructor(private http: HttpClient) { }

    getCurrentUser(): AuthUser | null {
        return this.currentUserSubject.value;
    }

    getAccessToken(): string | null {
        return localStorage.getItem(this.accessTokenKey);
    }

    getRefreshToken(): string | null {
        return localStorage.getItem(this.refreshTokenKey);
    }

    isAuthenticated(): boolean {
        return !!this.getAccessToken();
    }

    isAnonymousMode(): boolean {
        return localStorage.getItem(this.anonymousModeKey) === '1';
    }

    enterAnonymousMode(): void {
        this.clearSession(false);
        localStorage.setItem(this.anonymousModeKey, '1');
        this.currentUserSubject.next(null);
    }

    exitAnonymousMode(): void {
        const hadAnonymousMode = this.isAnonymousMode();
        localStorage.removeItem(this.anonymousModeKey);
        if (hadAnonymousMode) {
            this.currentUserSubject.next(this.currentUserSubject.value);
        }
    }

    register$(payload: AuthRegisterRequest): Observable<AuthUser> {
        return this.http.post<AuthTokenResponse>(`${this.apiUrl}/register`, payload).pipe(
            tap((response) => this.storeSession(response)),
            map((response) => response.user)
        );
    }

    login$(payload: AuthLoginRequest): Observable<AuthUser> {
        return this.http.post<AuthTokenResponse>(`${this.apiUrl}/login`, payload).pipe(
            tap((response) => this.storeSession(response)),
            map((response) => response.user)
        );
    }

    refresh$(): Observable<AuthTokenResponse | null> {
        const refreshToken = this.getRefreshToken();
        if (!refreshToken) {
            this.clearSession();
            return of(null);
        }

        if (this.refreshInFlight$) {
            return this.refreshInFlight$;
        }

        this.refreshInFlight$ = this.http
            .post<AuthTokenResponse>(`${this.apiUrl}/refresh`, { refresh_token: refreshToken })
            .pipe(
                tap((response) => this.storeSession(response)),
                catchError((error: HttpErrorResponse) => {
                    if ([400, 401].includes(error?.status)) {
                        this.clearSession();
                    }
                    return of(null);
                }),
                finalize(() => {
                    this.refreshInFlight$ = null;
                }),
                shareReplay(1)
            );
        return this.refreshInFlight$;
    }

    logout$(): Observable<boolean> {
        const refreshToken = this.getRefreshToken();
        if (!refreshToken) {
            this.clearSession();
            return of(true);
        }

        return this.http.post<{ revoked: boolean }>(`${this.apiUrl}/logout`, { refresh_token: refreshToken }).pipe(
            map((response) => !!response.revoked),
            catchError(() => of(false)),
            tap(() => {
                this.clearSession();
                this.exitAnonymousMode();
            })
        );
    }

    me$(): Observable<AuthUser | null> {
        return this.http.get<{ user: AuthUser }>(`${this.apiUrl}/me`).pipe(
            map((response) => response.user ?? null),
            tap((user) => {
                if (user) {
                    this.currentUserSubject.next(user);
                    localStorage.setItem(this.userKey, JSON.stringify(user));
                }
            }),
            catchError(() => of(null))
        );
    }

    /**
     * Patch UserSettings (language / timezone) for the currently authenticated
     * user. Source of truth for "generation language" used by all LLM calls
     * (resolve_user_language helper).
     */
    updateMeSettings$(payload: { language?: string; timezone?: string }): Observable<AuthUser | null> {
        return this.http.patch<{ user: AuthUser }>(`${this.apiUrl}/me/settings`, payload).pipe(
            map((response) => response.user ?? null),
            tap((user) => {
                if (user) {
                    this.currentUserSubject.next(user);
                    localStorage.setItem(this.userKey, JSON.stringify(user));
                }
            }),
            catchError(() => of(null))
        );
    }

    getBootstrapState$(forceRefresh: boolean = false): Observable<AuthBootstrapState> {
        const cached = this.bootstrapStateSubject.value;
        if (!forceRefresh && cached) {
            return of(cached);
        }

        return this.http.get<AuthBootstrapState>(`${this.apiUrl}/bootstrap-state`).pipe(
            tap((state) => this.storeBootstrapState(state)),
            catchError(() => {
                const fallback: AuthBootstrapState = {
                    has_owner: false,
                    requires_setup: true,
                    auth_users_count: 0,
                    first_registration_role: 'owner',
                    allow_anonymous: false,
                };
                this.storeBootstrapState(fallback);
                return of(fallback);
            })
        );
    }

    bootstrapSession$(): Observable<AuthUser | null> {
        if (!this.getAccessToken()) {
            this.clearSession();
            return of(null);
        }

        return this.me$().pipe(
            switchMap((user) => {
                if (user) {
                    return of(user);
                }
                return this.refresh$().pipe(
                    switchMap((res) => {
                        if (!res) {
                            return of(null);
                        }
                        return this.me$();
                    })
                );
            })
        );
    }

    clearSession(emit: boolean = true): void {
        localStorage.removeItem(this.accessTokenKey);
        localStorage.removeItem(this.refreshTokenKey);
        localStorage.removeItem(this.userKey);
        this.refreshInFlight$ = null;
        if (emit) {
            this.currentUserSubject.next(null);
        }
    }

    private storeBootstrapState(state: AuthBootstrapState): void {
        this.bootstrapStateSubject.next(state);
        localStorage.setItem(this.bootstrapStateKey, JSON.stringify(state));
    }

    private storeSession(response: AuthTokenResponse): void {
        if (!response?.access_token || !response?.refresh_token) {
            return;
        }

        this.exitAnonymousMode();
        localStorage.setItem(this.accessTokenKey, response.access_token);
        localStorage.setItem(this.refreshTokenKey, response.refresh_token);
        localStorage.setItem(this.userKey, JSON.stringify(response.user));
        const preferredLanguage = response.user?.settings?.language;
        if (preferredLanguage) {
            localStorage.setItem('language', preferredLanguage);
        }
        this.currentUserSubject.next(response.user);

        // First-run flow: once we have a valid authenticated user,
        // owner bootstrap is considered completed for guard checks.
        const currentBootstrap = this.bootstrapStateSubject.value;
        const nextBootstrap: AuthBootstrapState = {
            has_owner: true,
            requires_setup: false,
            auth_users_count: Math.max(1, currentBootstrap?.auth_users_count ?? 1),
            first_registration_role: 'user',
            allow_anonymous: true,
        };
        this.storeBootstrapState(nextBootstrap);
    }

    private loadStoredUser(): AuthUser | null {
        const raw = localStorage.getItem(this.userKey);
        if (!raw) {
            return null;
        }
        try {
            return JSON.parse(raw) as AuthUser;
        } catch {
            return null;
        }
    }

    private loadStoredBootstrapState(): AuthBootstrapState | null {
        const raw = localStorage.getItem(this.bootstrapStateKey);
        if (!raw) {
            return null;
        }
        try {
            return JSON.parse(raw) as AuthBootstrapState;
        } catch {
            return null;
        }
    }
}
