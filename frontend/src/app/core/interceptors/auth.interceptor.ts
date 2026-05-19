import { Injectable } from '@angular/core';
import {
    HttpErrorResponse,
    HttpEvent,
    HttpHandler,
    HttpInterceptor,
    HttpRequest,
} from '@angular/common/http';
import { Router } from '@angular/router';
import { Observable, throwError } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';
import { AuthService } from '../services/auth.service';

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
    constructor(private authService: AuthService, private router: Router) { }

    intercept(req: HttpRequest<unknown>, next: HttpHandler): Observable<HttpEvent<unknown>> {
        const token = this.authService.getAccessToken();
        const isApiRequest = req.url.includes('/api/');
        const isAuthEndpoint = req.url.includes('/api/auth/');
        const isRefreshEndpoint = req.url.includes('/api/auth/refresh');
        const alreadyRetried = req.headers.has('x-auth-retry');
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

        let requestToSend = req;
        if (isApiRequest && token && !isRefreshEndpoint) {
            requestToSend = req.clone({
                setHeaders: {
                    Authorization: `Bearer ${token}`,
                    'X-Client-Timezone': timezone,
                },
            });
        } else if (isApiRequest && !isRefreshEndpoint) {
            requestToSend = req.clone({
                setHeaders: {
                    'X-Client-Timezone': timezone,
                },
            });
        }

        return next.handle(requestToSend).pipe(
            catchError((error: HttpErrorResponse) => {
                const authRelated401 = this.isAuthRelated401(error);
                if (error.status === 401 && isApiRequest && authRelated401 && (isAuthEndpoint || alreadyRetried)) {
                    this.handleAuthFailure();
                    return throwError(() => error);
                }

                if (error.status !== 401 || !isApiRequest || isAuthEndpoint || alreadyRetried || !authRelated401) {
                    return throwError(() => error);
                }

                return this.authService.refresh$().pipe(
                    switchMap((refreshResponse) => {
                        if (!refreshResponse?.access_token) {
                            this.handleAuthFailure();
                            return throwError(() => error);
                        }

                        const retriedRequest = req.clone({
                            setHeaders: {
                                Authorization: `Bearer ${refreshResponse.access_token}`,
                                'X-Client-Timezone': timezone,
                                'x-auth-retry': '1',
                            },
                        });
                        return next.handle(retriedRequest);
                    }),
                    catchError((refreshError: HttpErrorResponse) => {
                        if ([400, 401].includes(refreshError?.status)) {
                            this.handleAuthFailure();
                        }
                        return throwError(() => refreshError);
                    })
                );
            })
        );
    }

    private isAuthRelated401(error: HttpErrorResponse): boolean {
        if (error.status !== 401) {
            return false;
        }

        const detail = this.extractErrorMessage(error);
        if (!detail) {
            return true;
        }

        const msg = detail.toLowerCase();
        const authHints = ['auth', 'authentication', 'token', 'unauthorized', 'expired', 'bearer', 'credentials'];
        const nonAuthHints = ['model', 'provider', 'ollama', 'openrouter', 'quota', 'rate limit', 'upstream', 'generation'];

        if (nonAuthHints.some((hint) => msg.includes(hint))) {
            return false;
        }
        if (authHints.some((hint) => msg.includes(hint))) {
            return true;
        }

        return false;
    }

    private extractErrorMessage(error: HttpErrorResponse): string {
        const payload = error?.error;
        if (typeof payload === 'string') {
            return payload;
        }
        if (payload && typeof payload === 'object') {
            const detail = (payload as any).detail;
            if (typeof detail === 'string') {
                return detail;
            }
            const message = (payload as any).message;
            if (typeof message === 'string') {
                return message;
            }
            const errorText = (payload as any).error;
            if (typeof errorText === 'string') {
                return errorText;
            }
        }
        if (typeof error?.message === 'string') {
            return error.message;
        }
        return '';
    }

    private handleAuthFailure(): void {
        this.authService.clearSession();
        this.authService.exitAnonymousMode();
        void this.router.navigateByUrl('/auth');
    }
}
