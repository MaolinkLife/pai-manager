import { ChangeDetectorRef, Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ApiService,
    OllamaPullState,
    OllamaRuntimeModel,
} from '../../../../core/services/api.service';
import { WebsocketService } from '../../../../core/services/websocket.service';
import { NotificationService } from '../../../../shared/components/notification/notification.service';
import { LocalizationService } from '../../../../shared/pipes/translation/localization.service';

/**
 * Model manager (/settings → Models, 0.9.3 block A part 1).
 *
 * Installed Ollama models with size / loaded state and unload / update /
 * delete actions, plus pull-by-name with live progress. Progress arrives as
 * `model_pull` WS events from the backend pull manager; the snapshot endpoint
 * restores active pulls after a page refresh.
 */
@Component({
    selector: 'app-models-settings',
    templateUrl: './models-settings.component.html',
    styleUrls: ['./models-settings.component.less'],
})
export class ModelsSettingsComponent implements OnInit {
    private readonly destroyRef = inject(DestroyRef);

    models: OllamaRuntimeModel[] = [];
    pulls: OllamaPullState[] = [];
    loading = false;
    pullName = '';
    pullStartPending = false;
    confirmDeleteModel: string | null = null;
    busyModels = new Set<string>();

    constructor(
        private apiService: ApiService,
        private websocketService: WebsocketService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {}

    ngOnInit(): void {
        this.localizationService.init();
        this.refresh();
        this.loadPulls();

        this.websocketService.messages$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((raw) => {
                try {
                    const event = JSON.parse(raw);
                    if (event?.type === 'model_pull' && event?.model) {
                        this.applyPullEvent(event as OllamaPullState);
                    }
                } catch {
                    // ignore non-json ws payloads
                }
            });
    }

    t(key: string): string {
        return this.localizationService.t(key);
    }

    refresh(): void {
        this.loading = true;
        this.apiService.getOllamaRuntimeModels$().subscribe((response) => {
            this.models = Array.isArray(response?.models) ? response.models : [];
            this.loading = false;
            this.cdr.markForCheck();
        });
    }

    trackByModel(_index: number, item: OllamaRuntimeModel): string {
        return item.name;
    }

    trackByPull(_index: number, item: OllamaPullState): string {
        return item.model;
    }

    formatSize(bytes?: number | null): string {
        const value = Number(bytes || 0);
        if (!value) {
            return '—';
        }
        const gb = value / (1024 ** 3);
        if (gb >= 1) {
            return `${gb.toFixed(1)} GB`;
        }
        return `${(value / (1024 ** 2)).toFixed(0)} MB`;
    }

    pullPercent(pull: OllamaPullState): number {
        if (!pull.total) {
            return 0;
        }
        return Math.min(100, Math.round((pull.completed / pull.total) * 100));
    }

    activePulls(): OllamaPullState[] {
        return this.pulls.filter((pull) => !pull.done);
    }

    startPull(name?: string): void {
        const model = String(name ?? this.pullName ?? '').trim();
        if (!model || this.pullStartPending) {
            return;
        }
        this.pullStartPending = true;
        this.apiService.pullOllamaModel$(model).subscribe((response) => {
            this.pullStartPending = false;
            if (!response || response.status === 'error') {
                this.notificationService.open({
                    type: 'error',
                    message: this.t('settingsPage.models.pullStartError'),
                    autoClose: true,
                });
            } else {
                if (!name) {
                    this.pullName = '';
                }
                this.loadPulls();
            }
            this.cdr.markForCheck();
        });
    }

    cancelPull(model: string): void {
        this.apiService.cancelOllamaPull$(model).subscribe(() => this.loadPulls());
    }

    dismissPull(model: string): void {
        this.pulls = this.pulls.filter((pull) => pull.model !== model);
        this.cdr.markForCheck();
    }

    unload(model: string): void {
        this.withBusy(model, () =>
            this.apiService.unloadOllamaModel$(model).subscribe(() => {
                this.busyModels.delete(model);
                this.refresh();
            })
        );
    }

    requestDelete(model: string): void {
        this.confirmDeleteModel = model;
    }

    cancelDelete(): void {
        this.confirmDeleteModel = null;
    }

    confirmDelete(): void {
        const model = this.confirmDeleteModel;
        this.confirmDeleteModel = null;
        if (!model) {
            return;
        }
        this.withBusy(model, () =>
            this.apiService.deleteOllamaModel$(model).subscribe((response) => {
                this.busyModels.delete(model);
                if (!response || response.status !== 'ok') {
                    this.notificationService.open({
                        type: 'error',
                        message: this.t('settingsPage.models.deleteError'),
                        autoClose: true,
                    });
                } else {
                    this.notificationService.open({
                        type: 'success',
                        message: this.t('settingsPage.models.deleted'),
                        autoClose: true,
                    });
                }
                this.refresh();
            })
        );
    }

    isBusy(model: string): boolean {
        return this.busyModels.has(model) || this.pulls.some(
            (pull) => pull.model === model && !pull.done
        );
    }

    private withBusy(model: string, action: () => void): void {
        if (this.isBusy(model)) {
            return;
        }
        this.busyModels.add(model);
        action();
    }

    private loadPulls(): void {
        this.apiService.getOllamaPulls$().subscribe((pulls) => {
            // Keep finished entries already dismissed by the user out of view.
            this.pulls = pulls;
            this.cdr.markForCheck();
        });
    }

    private applyPullEvent(event: OllamaPullState): void {
        const index = this.pulls.findIndex((pull) => pull.model === event.model);
        if (index === -1) {
            this.pulls = [...this.pulls, event];
        } else {
            const next = [...this.pulls];
            next[index] = { ...next[index], ...event };
            this.pulls = next;
        }
        if (event.done && !event.error && event.status === 'success') {
            this.refresh();
        }
        this.cdr.markForCheck();
    }
}
