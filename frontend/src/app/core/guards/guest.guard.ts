import { Injectable } from '@angular/core';
import {
    ActivatedRouteSnapshot,
    CanActivate,
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
export class GuestGuard implements CanActivate {
    constructor(private authService: AuthService, private router: Router) { }

    canActivate(
        _route: ActivatedRouteSnapshot,
        _state: RouterStateSnapshot
    ): Observable<boolean | UrlTree> {
        return this.authService.getBootstrapState$().pipe(
            switchMap((bootstrap) => {
                // First-run: always allow auth page so first account can be created.
                if (!bootstrap?.has_owner) {
                    this.authService.clearSession();
                    this.authService.exitAnonymousMode();
                    return of(true);
                }

                if (this.authService.isAnonymousMode()) {
                    return of(this.router.parseUrl('/chat'));
                }

                if (!this.authService.getAccessToken()) {
                    return of(true);
                }

                return this.authService.bootstrapSession$().pipe(
                    map((user) => (user ? this.router.parseUrl('/chat') : true)),
                    catchError(() => of(true))
                );
            }),
            catchError(() => of(true))
        );
    }
}
