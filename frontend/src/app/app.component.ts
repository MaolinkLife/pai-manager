import { Component, DestroyRef, OnInit, inject } from '@angular/core';
import { WebsocketService } from './core/services/websocket.service';
import { LocalizationService } from './shared/pipes/translation/localization.service';
import { AuthService } from './core/services/auth.service';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

@Component({
    selector: 'app-root',
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.less']
})
export class AppComponent implements OnInit {
    private readonly destroyRef = inject(DestroyRef);
    title = 'z-waif-project';

    constructor(
        private websocketService: WebsocketService,
        private localizationService: LocalizationService,
        private authService: AuthService
    ) {

    }

    ngOnInit() {
        this.localizationService.init();
        let lastAccessToken = this.authService.getAccessToken();
        let lastAnonymousMode = this.authService.isAnonymousMode();
        this.authService.currentUser$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(() => {
                const nextToken = this.authService.getAccessToken();
                const nextAnonymousMode = this.authService.isAnonymousMode();
                if (nextToken !== lastAccessToken || nextAnonymousMode !== lastAnonymousMode) {
                    lastAccessToken = nextToken;
                    lastAnonymousMode = nextAnonymousMode;
                    if (nextToken || nextAnonymousMode) {
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
