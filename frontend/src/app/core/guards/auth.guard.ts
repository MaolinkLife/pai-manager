import { Injectable } from '@angular/core';
import {
    ActivatedRouteSnapshot,
    CanActivate,
    CanActivateChild,
    Router,
    RouterStateSnapshot,
    UrlTree,
} from '@angular/router';
import { Observable, of } from 'rxjs';
import { catchError, map, switchMap } from 'rxjs/operators';
import { AuthService } from '../services/auth.service';

@Injectable({
    providedIn: 'root',
})
export class AuthGuard implements CanActivate, CanActivateChild {
    constructor(private authService: AuthService, private router: Router) { }

    canActivate(
        _route: ActivatedRouteSnapshot,
        state: RouterStateSnapshot
    ): Observable<boolean | UrlTree> {
        return this.checkAccess$(undefined, state);
    }

    canActivateChild(
        childRoute: ActivatedRouteSnapshot,
        state: RouterStateSnapshot
    ): Observable<boolean | UrlTree> {
        return this.checkAccess$(childRoute.routeConfig?.path || '', state);
    }

    private checkAccess$(
        routePath?: string,
        state?: RouterStateSnapshot
    ): Observable<boolean | UrlTree> {
        return this.authService.getBootstrapState$().pipe(
            switchMap((bootstrap) => {
                if (!bootstrap?.has_owner) {
                    this.authService.clearSession();
                    this.authService.exitAnonymousMode();
                    return of(this.router.parseUrl('/auth'));
                }

                if (this.authService.isAnonymousMode()) {
                    if (!bootstrap.allow_anonymous) {
                        this.authService.exitAnonymousMode();
                        return of(this.router.parseUrl('/auth'));
                    }
                    const resolvedPath = (routePath || '').toLowerCase();
                    const targetUrl = this.normalizePath(state?.url || '');
                    const isChatRoute =
                        resolvedPath === 'chat' ||
                        targetUrl === '/chat' ||
                        targetUrl.startsWith('/chat/');
                    if (!isChatRoute && targetUrl !== '/' && targetUrl !== '') {
                        return of(this.router.parseUrl('/chat'));
                    }
                    return of(true);
                }

                if (!this.authService.getAccessToken()) {
                    return of(this.router.parseUrl('/auth'));
                }

                return this.authService.bootstrapSession$().pipe(
                    map((user) => (user ? true : this.router.parseUrl('/auth'))),
                    catchError(() => of(this.router.parseUrl('/auth')))
                );
            }),
            catchError(() => of(this.router.parseUrl('/auth')))
        );
    }

    private normalizePath(url: string): string {
        if (!url) {
            return '';
        }
        const [path] = url.split(/[?#]/, 1);
        return (path || '').toLowerCase();
    }
}
