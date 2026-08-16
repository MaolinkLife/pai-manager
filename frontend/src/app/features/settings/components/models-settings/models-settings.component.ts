import { ChangeDetectorRef, Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    ApiService,
    HfDownloadState,
    HfRepoFile,
    HfSearchResult,
    LocalModelResourceItem,
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

    hfQuery = '';
    hfSearching = false;
    hfResults: HfSearchResult[] = [];
    hfSelectedRepo: string | null = null;
    hfFiles: HfRepoFile[] = [];
    hfFilesLoading = false;
    hfFilesError = '';
    hfDownloads: HfDownloadState[] = [];
    hfFileCategories: Record<string, string> = {};

    private readonly hfCategoryKeys = [
        'gguf', 'image_checkpoint', 'image_lora', 'image_vae', 'stt', 'tts', 'vision', 'rvc',
    ];
    hfCategoryOptions: Array<{ label: string; value: string }> = [];

    storageGroups: Array<{ key: string; items: LocalModelResourceItem[] }> = [];
    storageLoading = false;
    confirmStorageDelete: LocalModelResourceItem | null = null;

    // Session-only HF token for gated/private repos (never persisted).
    hfToken = '';
    hfTokenPromptOpen = false;
    hfTokenInput = '';
    private hfTokenRetryRepo: string | null = null;

    constructor(
        private apiService: ApiService,
        private websocketService: WebsocketService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {}

    ngOnInit(): void {
        this.localizationService.init();
        this.hfCategoryOptions = this.hfCategoryKeys.map((key) => ({
            label: this.t(`settingsPage.models.hfCategories.${key}`),
            value: key,
        }));
        this.refresh();
        this.loadPulls();
        this.loadHfDownloads();
        this.refreshStorage();

        this.websocketService.messages$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((raw) => {
                try {
                    const event = JSON.parse(raw);
                    if (event?.type === 'model_pull' && event?.model) {
                        this.applyPullEvent(event as OllamaPullState);
                    } else if (event?.type === 'hf_download' && event?.id) {
                        this.applyHfEvent(event as HfDownloadState);
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

    searchHf(): void {
        const query = this.hfQuery.trim();
        if (query.length < 2 || this.hfSearching) {
            return;
        }
        this.hfSearching = true;
        this.hfSelectedRepo = null;
        this.hfFiles = [];
        this.apiService.searchHfModels$(query).subscribe((results) => {
            this.hfResults = results;
            this.hfSearching = false;
            this.cdr.markForCheck();
        });
    }

    selectHfRepo(repo: string): void {
        if (this.hfSelectedRepo === repo) {
            this.hfSelectedRepo = null;
            this.hfFiles = [];
            return;
        }
        this.hfSelectedRepo = repo;
        this.loadHfFiles(repo);
    }

    private loadHfFiles(repo: string): void {
        this.hfFiles = [];
        this.hfFilesError = '';
        this.hfFilesLoading = true;
        this.apiService.getHfRepoFiles$(repo, this.hfToken || undefined).subscribe((response) => {
            this.hfFilesLoading = false;
            if (!response || response.status !== 'ok') {
                if (response?.code === 'gated') {
                    // Token prompt: a valid token makes the listing succeed,
                    // which doubles as token validation.
                    this.hfTokenRetryRepo = repo;
                    this.hfTokenInput = this.hfToken;
                    this.hfTokenPromptOpen = true;
                    this.hfFilesError = this.t('settingsPage.models.hfGatedHint');
                } else {
                    this.hfFilesError = response?.message || this.t('settingsPage.models.hfFilesError');
                }
            } else {
                this.hfFiles = response.files;
                for (const file of this.hfFiles) {
                    this.hfFileCategories[file.path] = file.suggested_category;
                }
            }
            this.cdr.markForCheck();
        });
    }

    submitHfToken(): void {
        const token = this.hfTokenInput.trim();
        this.hfTokenPromptOpen = false;
        if (!token) {
            return;
        }
        this.hfToken = token;
        const repo = this.hfTokenRetryRepo;
        this.hfTokenRetryRepo = null;
        if (repo && this.hfSelectedRepo === repo) {
            this.loadHfFiles(repo);
        }
    }

    cancelHfToken(): void {
        this.hfTokenPromptOpen = false;
        this.hfTokenRetryRepo = null;
    }

    hfDownloadFile(file: HfRepoFile): void {
        const repo = this.hfSelectedRepo;
        if (!repo) {
            return;
        }
        const category = this.hfFileCategories[file.path] || file.suggested_category;
        this.apiService.startHfDownload$(repo, file.path, category, this.hfToken || undefined).subscribe((response) => {
            if (!response) {
                this.notificationService.open({
                    type: 'error',
                    message: this.t('settingsPage.models.hfDownloadStartError'),
                    autoClose: true,
                });
            } else {
                this.loadHfDownloads();
            }
            this.cdr.markForCheck();
        });
    }

    cancelHfDownload(id: string): void {
        this.apiService.cancelHfDownload$(id).subscribe(() => this.loadHfDownloads());
    }

    dismissHfDownload(id: string): void {
        this.hfDownloads = this.hfDownloads.filter((item) => item.id !== id);
        this.cdr.markForCheck();
    }

    isHfFileDownloading(file: HfRepoFile): boolean {
        const repo = this.hfSelectedRepo;
        if (!repo) {
            return false;
        }
        const key = `${repo}::${file.path}`;
        return this.hfDownloads.some((item) => item.id === key && !item.done);
    }

    hfPercent(item: HfDownloadState): number {
        if (!item.total) {
            return 0;
        }
        return Math.min(100, Math.round((item.completed / item.total) * 100));
    }

    hfFileName(path: string): string {
        const parts = path.split('/');
        return parts[parts.length - 1] || path;
    }

    trackByHfResult(_index: number, item: HfSearchResult): string {
        return item.repo_id;
    }

    trackByHfFile(_index: number, item: HfRepoFile): string {
        return item.path;
    }

    trackByHfDownload(_index: number, item: HfDownloadState): string {
        return item.id;
    }

    formatDownloads(count: number): string {
        if (count >= 1_000_000) {
            return `${(count / 1_000_000).toFixed(1)}M`;
        }
        if (count >= 1_000) {
            return `${(count / 1_000).toFixed(0)}k`;
        }
        return String(count);
    }

    refreshStorage(): void {
        this.storageLoading = true;
        this.apiService.getLocalModels$().subscribe((response) => {
            const groups = response?.groups || {};
            this.storageGroups = Object.keys(groups)
                .map((key) => ({ key, items: groups[key] || [] }))
                .filter((group) => group.items.length > 0);
            this.storageLoading = false;
            this.cdr.markForCheck();
        });
    }

    storageGroupLabel(key: string): string {
        const label = this.t(`settingsPage.models.storageGroups.${key}`);
        return label.startsWith('settingsPage.') ? key : label;
    }

    requestStorageDelete(item: LocalModelResourceItem): void {
        this.confirmStorageDelete = item;
    }

    cancelStorageDelete(): void {
        this.confirmStorageDelete = null;
    }

    confirmStorageDeleteAction(): void {
        const item = this.confirmStorageDelete;
        this.confirmStorageDelete = null;
        if (!item?.absolute_path) {
            return;
        }
        this.apiService.deleteLocalModelFile$(item.absolute_path).subscribe((response) => {
            if (!response || response.status !== 'ok') {
                this.notificationService.open({
                    type: 'error',
                    message: response?.message || this.t('settingsPage.models.deleteError'),
                    autoClose: true,
                });
            } else {
                this.notificationService.open({
                    type: 'success',
                    message: this.t('settingsPage.models.storageDeleted'),
                    autoClose: true,
                });
            }
            this.refreshStorage();
        });
    }

    trackByStorageGroup(_index: number, group: { key: string }): string {
        return group.key;
    }

    trackByStorageItem(_index: number, item: LocalModelResourceItem): string {
        return item.absolute_path || item.id;
    }

    private loadHfDownloads(): void {
        this.apiService.getHfDownloads$().subscribe((downloads) => {
            this.hfDownloads = downloads;
            this.cdr.markForCheck();
        });
    }

    private applyHfEvent(event: HfDownloadState): void {
        const index = this.hfDownloads.findIndex((item) => item.id === event.id);
        if (index === -1) {
            this.hfDownloads = [...this.hfDownloads, event];
        } else {
            const next = [...this.hfDownloads];
            next[index] = { ...next[index], ...event };
            this.hfDownloads = next;
        }
        if (event.done && event.status === 'success') {
            this.notificationService.open({
                type: 'success',
                message: `${this.t('settingsPage.models.hfDownloaded')}: ${this.hfFileName(event.path)}`,
                autoClose: true,
            });
            this.refreshStorage();
        }
        this.cdr.markForCheck();
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
