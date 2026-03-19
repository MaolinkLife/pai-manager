import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, CanActivate, Router, RouterStateSnapshot, UrlTree } from '@angular/router';
import { Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { AuthService } from '../services/auth.service';

@Injectable({
    providedIn: 'root',
})
export class AuthenticatedUserGuard implements CanActivate {
    constructor(private authService: AuthService, private router: Router) { }

    canActivate(
        _route: ActivatedRouteSnapshot,
        _state: RouterStateSnapshot
    ): Observable<boolean | UrlTree> {
        if (this.authService.isAnonymousMode()) {
            return of(this.router.parseUrl('/chat'));
        }

        if (!this.authService.getAccessToken()) {
            return of(this.router.parseUrl('/auth'));
        }

        return this.authService.bootstrapSession$().pipe(
            map((user) => (user ? true : this.router.parseUrl('/auth'))),
            catchError(() => of(this.router.parseUrl('/auth')))
        );
    }
}
