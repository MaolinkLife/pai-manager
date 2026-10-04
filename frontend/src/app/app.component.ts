import { Component, DestroyRef, OnInit, inject } from '@angular/core';
import { WebsocketService } from './core/services/websocket.service';
import { LocalizationService } from './shared/pipes/translation/localization.service';
import { AuthService } from './core/services/auth.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

@Component({
    selector: 'app-root',
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.less'],
    standalone: false
})
export class AppComponent implements OnInit {
    private readonly destroyRef = inject(DestroyRef);
    title = 'pai-manager';

    constructor(
        private websocketService: WebsocketService,
        private localizationService: LocalizationService,
        private authService: AuthService
    ) {

    }

    ngOnInit() {
        this.localizationService.init();
        // The socket follows who is signed in, not the access token: a token that is
        // only renewed keeps the connection, and a reply being written, as they are.
        const identity = (): string | null => {
            if (this.authService.isAnonymousMode()) {
                return 'anonymous';
            }
            if (!this.authService.getAccessToken()) {
                return null;
            }
            return this.authService.getCurrentUser()?.uuid ?? 'signed-in';
        };
        let lastIdentity = identity();
        this.authService.currentUser$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                const nextIdentity = identity();
                if (nextIdentity !== lastIdentity) {
                    lastIdentity = nextIdentity;
                    if (nextIdentity) {
                        this.websocketService.reconnect();
                    } else {
                        this.websocketService.disconnect();
                    }
                }
            });

        this.authService.bootstrapSession$().subscribe({
            next: () => {
                if (this.authService.isAuthenticated() || this.authService.isAnonymousMode()) {
                    this.websocketService.connect();
                } else {
                    this.websocketService.disconnect();
                }
            },
            error: () => this.websocketService.disconnect(),
        });
    }
}
