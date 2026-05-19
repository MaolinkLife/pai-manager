import { Component, OnDestroy, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { ModalService } from '../shared/components/modal/modal.service';
import { MemoryModalComponent } from './components/modals/memory-modal/memory-modal.component';
import { MOCK_LOREBOOK } from '../shared/mock/lorebook-mock';
import { MainModalComponent } from './components/modals/main-modal/main-modal.component';
import { NotificationService } from '../shared/components/notification/notification.service';
import { ThemeService } from '../core/services/theme.service';
import { ConfigService } from '../core/services/config.service';
import { ApiService, OllamaRuntimeModel } from '../core/services/api.service';
import { ProjectConfig } from '../core/models/project-config.model';
import { filter } from 'rxjs/operators';
import { UiFeatureFlagsService } from '../core/services/ui-feature-flags.service';
import { AuthService } from '../core/services/auth.service';
import { AuthUser } from '../core/models/auth.model';
import { LocalizationService } from '../shared/pipes/translation/localization.service';

@Component({
    selector: 'app-layout',
    templateUrl: './layout.component.html',
    styleUrls: ['./layout.component.less']
})
export class LayoutComponent implements OnInit, OnDestroy {
    private static readonly CHAT_ALL_SOURCES_KEY = 'chat.showAllSources';

    currentTheme: 'dark' | 'light' = 'dark';
    isChatRoute = false;
    generationPanelOpen = false;
    entityPanelOpen = false;
    generationPanelLoading = false;
    generationPanelSaving = false;
    generationProvider = 'ollama';
    generationProviderOptions: string[] = [];
    generationModel = '';
    generationModels: string[] = [];
    generationRuntimeModels: OllamaRuntimeModel[] = [];
    generationRuntimeLoading = false;
    generationRuntimeUnloading = false;
    generationTemperature = 1.0;
    generationTopP = 0.9;
    generationTopK = 40;
    generationMaxTokens = 1024;
    showAllChatSources = false;
    uiFlags = { audit: false, diary: false, tasks: false };
    profileMenuOpen = false;
    currentUser: AuthUser | null = null;
    anonymousMode = false;
    private generationConfigSnapshot: ProjectConfig | null = null;
    private generationRuntimeRefreshTimer: ReturnType<typeof setInterval> | null = null;

    constructor(
        private modalService: ModalService,
        private notificationService: NotificationService,
        private theme: ThemeService,
        private configService: ConfigService,
        private apiService: ApiService,
        private authService: AuthService,
        private uiFeatureFlags: UiFeatureFlagsService,
        private localizationService: LocalizationService,
        private router: Router
    ) { }

    ngOnInit(): void {
        this.currentTheme = this.theme.getTheme();
        this.theme.initTheme();
        this.localizationService.init();
        this.showAllChatSources = this.readShowAllChatSources();
        this.uiFlags = this.uiFeatureFlags.all();
        this.updateChatRouteState(this.router.url);
        this.router.events
            .pipe(filter((event) => event instanceof NavigationEnd))
            .subscribe((event) => {
                this.updateChatRouteState((event as NavigationEnd).urlAfterRedirects);
            });

        this.authService.currentUser$.subscribe((user) => {
            this.currentUser = user;
            this.anonymousMode = this.authService.isAnonymousMode();
            if (this.anonymousMode) {
                this.generationPanelOpen = false;
                this.entityPanelOpen = false;
            }
        });
    }

    ngOnDestroy(): void {
        this.stopGenerationRuntimeRefresh();
    }

    toggleTheme() {
        this.theme.toggleTheme();
        this.currentTheme = this.theme.getTheme();
    }

    memoryClick() {
        this.modalService.open(MainModalComponent, {
            title: this.t('settingsSidebar.title'),
            data: { entries: [] }
        }).afterClosed$.subscribe(updated => {
            console.log('Сохранено:', updated);
        });
    }

    openSettingsModal() {
        this.modalService.open(MainModalComponent, {
            title: this.t('settingsSidebar.title'),
            data: { entries: [] }
        }).afterClosed$.subscribe(updated => {
            console.log('Сохранено:', updated);
        });
    }

    t(key: string): string {
        return this.localizationService.t(key);
    }

    toggleGenerationPanel(): void {
        this.generationPanelOpen = !this.generationPanelOpen;
        if (this.generationPanelOpen) {
            this.loadQuickGenerationSettings();
        } else {
            this.stopGenerationRuntimeRefresh();
        }
    }

    closeGenerationPanel(): void {
        this.generationPanelOpen = false;
        this.stopGenerationRuntimeRefresh();
    }

    toggleEntityPanel(): void {
        this.entityPanelOpen = !this.entityPanelOpen;
    }

    closeEntityPanel(): void {
        this.entityPanelOpen = false;
    }

    toggleProfileMenu(): void {
        this.profileMenuOpen = !this.profileMenuOpen;
    }

    logout(): void {
        this.authService.logout$().subscribe({
            next: () => {
                this.profileMenuOpen = false;
                this.router.navigateByUrl('/auth');
            },
            error: () => {
                this.profileMenuOpen = false;
                this.router.navigateByUrl('/auth');
            },
        });
    }

    goToAuth(): void {
        this.profileMenuOpen = false;
        this.authService.exitAnonymousMode();
        this.router.navigateByUrl('/auth');
    }

    canManageSettings(): boolean {
        return !this.anonymousMode && !!this.currentUser;
    }

    getProfileInitials(): string {
        if (this.anonymousMode) {
            return 'A';
        }
        const source = this.currentUser?.name || this.currentUser?.login || this.currentUser?.email || 'U';
        const normalized = source.trim();
        if (!normalized) {
            return 'U';
        }
        return normalized.slice(0, 1).toUpperCase();
    }

    private updateChatRouteState(url: string): void {
        this.isChatRoute = /^\/?chat(\/|$)/.test(url || '');
        if (!this.isChatRoute) {
            this.generationPanelOpen = false;
        }
    }

    private loadQuickGenerationSettings(): void {
        if (this.generationPanelLoading) {
            return;
        }

        this.generationPanelLoading = true;
        this.configService.getConfig$().subscribe({
            next: (config) => {
                if (!config) {
                    this.generationPanelLoading = false;
                    return;
                }

                this.generationConfigSnapshot = config;
                const provider = config.api?.activeProvider || 'ollama';
                this.generationProviderOptions = Object.keys(config.api?.providers || {});
                const providerConfig = config.api?.providers?.[provider];
                const model = providerConfig?.model || config.api?.model || '';
                const temperatureFromProvider = providerConfig?.temperature;
                const temperatureFromGeneration = config.generateSettings?.temperature;
                const maxTokensFromProvider = providerConfig?.maxTokens;
                const maxTokensFromGeneration = config.generateSettings?.numPredict;

                this.generationProvider = provider;
                this.generationModel = model;
                this.generationTemperature = Number(
                    temperatureFromGeneration ?? temperatureFromProvider ?? 1.0
                );
                this.generationTopP = Number(config.generateSettings?.topP ?? 0.9);
                this.generationTopK = Number(config.generateSettings?.topK ?? 40);
                this.generationMaxTokens = Number(
                    maxTokensFromGeneration ?? maxTokensFromProvider ?? 1024
                );
                this.showAllChatSources = this.readShowAllChatSources();

                if (provider === 'ollama') {
                    this.apiService.getOllamaModels$().subscribe({
                        next: (models) => {
                            const modelSet = new Set(models || []);
                            if (this.generationModel) {
                                modelSet.add(this.generationModel);
                            }
                            this.generationModels = Array.from(modelSet);
                            this.generationPanelLoading = false;
                            this.refreshOllamaRuntimeState();
                            this.startGenerationRuntimeRefresh();
                        },
                        error: () => {
                            this.generationModels = this.generationModel ? [this.generationModel] : [];
                            this.generationPanelLoading = false;
                            this.startGenerationRuntimeRefresh();
                        }
                    });
                    return;
                }

                this.generationModels = this.generationModel ? [this.generationModel] : [];
                this.generationRuntimeModels = [];
                this.stopGenerationRuntimeRefresh();
                this.generationPanelLoading = false;
            },
            error: () => {
                this.generationPanelLoading = false;
            }
        });
    }

    onQuickGenerationProviderChange(provider: string): void {
        this.generationProvider = provider;
        const providerConfig = this.generationConfigSnapshot?.api?.providers?.[provider];
        this.generationModel = providerConfig?.model || '';
        this.generationTemperature = Number(
            this.generationConfigSnapshot?.generateSettings?.temperature
            ?? providerConfig?.temperature
            ?? this.generationTemperature
        );
        this.generationMaxTokens = Number(
            this.generationConfigSnapshot?.generateSettings?.numPredict
            ?? providerConfig?.maxTokens
            ?? this.generationMaxTokens
        );
        this.loadQuickProviderModels(provider);
        if (provider === 'ollama') {
            this.refreshOllamaRuntimeState();
            this.startGenerationRuntimeRefresh();
        } else {
            this.generationRuntimeModels = [];
            this.stopGenerationRuntimeRefresh();
        }
    }

    onQuickGenerationModelChange(model: string): void {
        this.generationModel = model;
        if (this.generationProvider === 'ollama') {
            this.refreshOllamaRuntimeState();
        }
    }

    unloadSelectedOllamaModel(): void {
        if (
            this.generationProvider !== 'ollama'
            || !this.generationModel
            || this.generationRuntimeUnloading
        ) {
            return;
        }

        const model = this.generationModel;
        this.generationRuntimeUnloading = true;
        this.apiService.unloadOllamaModel$(model).subscribe({
            next: (response) => {
                this.generationRuntimeUnloading = false;
                if (response?.status === 'ok') {
                    this.notificationService.open({
                        type: 'success',
                        title: 'Ollama model unloaded',
                        message: model,
                        autoClose: true,
                    });
                    this.refreshOllamaRuntimeState();
                    return;
                }

                this.notificationService.open({
                    type: 'error',
                    title: 'Failed to unload Ollama model',
                    message: response?.message || model,
                    autoClose: true,
                });
            },
            error: () => {
                this.generationRuntimeUnloading = false;
                this.notificationService.open({
                    type: 'error',
                    title: 'Failed to unload Ollama model',
                    message: model,
                    autoClose: true,
                });
            },
        });
    }

    get selectedOllamaRuntimeModel(): OllamaRuntimeModel | null {
        if (this.generationProvider !== 'ollama' || !this.generationModel) {
            return null;
        }
        const selected = this.generationModel.trim();
        return this.generationRuntimeModels.find((item) => {
            const name = String(item.name || item.model || '').trim();
            return name === selected;
        }) || null;
    }

    get isSelectedOllamaModelLoaded(): boolean {
        return !!this.selectedOllamaRuntimeModel?.loaded;
    }

    get ollamaRuntimeLabel(): string {
        if (this.generationProvider !== 'ollama') {
            return '';
        }
        if (this.generationRuntimeLoading) {
            return 'Проверяю состояние модели';
        }
        if (!this.generationModel) {
            return 'Модель не выбрана';
        }
        const runtimeModel = this.selectedOllamaRuntimeModel;
        if (!runtimeModel) {
            return 'Статус модели неизвестен';
        }
        if (runtimeModel.loaded) {
            return runtimeModel.expires_at
                ? `Модель загружена в память до ${runtimeModel.expires_at}`
                : 'Модель загружена в память';
        }
        return 'Модель не загружена в память';
    }

    get ollamaRuntimeState(): 'loading' | 'loaded' | 'idle' | 'unknown' {
        if (this.generationRuntimeLoading) {
            return 'loading';
        }
        if (!this.generationModel) {
            return 'unknown';
        }
        const runtimeModel = this.selectedOllamaRuntimeModel;
        if (!runtimeModel) {
            return 'unknown';
        }
        return runtimeModel.loaded ? 'loaded' : 'idle';
    }

    get ollamaRuntimeBadgeText(): string {
        if (this.ollamaRuntimeState === 'loading') {
            return 'проверка';
        }
        if (this.ollamaRuntimeState === 'loaded') {
            return 'в памяти';
        }
        if (this.ollamaRuntimeState === 'idle') {
            return 'не загружена';
        }
        return 'статус неизвестен';
    }

    private loadQuickProviderModels(provider: string): void {
        if (provider === 'ollama') {
            this.generationPanelLoading = true;
            this.apiService.getOllamaModels$().subscribe({
                next: (models) => {
                    const modelSet = new Set(models || []);
                    if (this.generationModel) {
                        modelSet.add(this.generationModel);
                    }
                    this.generationModels = Array.from(modelSet);
                    this.generationPanelLoading = false;
                    this.refreshOllamaRuntimeState();
                },
                error: () => {
                    this.generationModels = this.generationModel ? [this.generationModel] : [];
                    this.generationPanelLoading = false;
                }
            });
            return;
        }

        this.generationModels = this.generationModel ? [this.generationModel] : [];
        this.generationPanelLoading = false;
    }

    private refreshOllamaRuntimeState(): void {
        if (this.generationProvider !== 'ollama' || this.generationRuntimeLoading) {
            return;
        }
        this.generationRuntimeLoading = true;
        this.apiService.getOllamaRuntimeModels$().subscribe({
            next: (response) => {
                this.generationRuntimeLoading = false;
                this.generationRuntimeModels = response?.status === 'ok' && Array.isArray(response.models)
                    ? response.models
                    : [];
            },
            error: () => {
                this.generationRuntimeLoading = false;
                this.generationRuntimeModels = [];
            },
        });
    }

    private startGenerationRuntimeRefresh(): void {
        if (this.generationProvider !== 'ollama' || this.generationRuntimeRefreshTimer) {
            return;
        }
        this.refreshOllamaRuntimeState();
        this.generationRuntimeRefreshTimer = setInterval(() => {
            if (!this.generationPanelOpen || this.generationProvider !== 'ollama') {
                this.stopGenerationRuntimeRefresh();
                return;
            }
            this.refreshOllamaRuntimeState();
        }, 7000);
    }

    private stopGenerationRuntimeRefresh(): void {
        if (!this.generationRuntimeRefreshTimer) {
            return;
        }
        clearInterval(this.generationRuntimeRefreshTimer);
        this.generationRuntimeRefreshTimer = null;
    }

    saveQuickGenerationSettings(): void {
        if (this.generationPanelSaving || !this.generationConfigSnapshot) {
            return;
        }

        const currentConfig = this.generationConfigSnapshot;
        const provider = this.generationProvider;
        const providers = { ...(currentConfig.api.providers || {}) };
        const currentProviderConfig = providers[provider] || {
            model: this.generationModel,
            temperature: this.generationTemperature,
            maxTokens: this.generationMaxTokens,
        };

        providers[provider] = {
            ...currentProviderConfig,
            model: this.generationModel,
            temperature: this.generationTemperature,
            maxTokens: this.generationMaxTokens,
        };

        const apiUpdate = {
            ...currentConfig.api,
            model: this.generationModel,
            activeProvider: provider,
            providers,
        };

        const generationUpdate = {
            ...currentConfig.generateSettings,
            temperature: this.generationTemperature,
            topP: this.generationTopP,
            topK: this.generationTopK,
            numPredict: this.generationMaxTokens,
        };
        const showAllSources = !!this.showAllChatSources;

        this.generationPanelSaving = true;
        this.configService.updateConfig$({
            api: apiUpdate,
            generateSettings: generationUpdate,
        }).subscribe({
            next: () => {
                this.persistShowAllChatSources(showAllSources);
                window.dispatchEvent(new CustomEvent('chat-history-source-filter-changed', {
                    detail: { showAllSources },
                }));
                this.notificationService.open({
                    type: 'success',
                    title: 'Generation settings updated',
                    autoClose: true,
                });
                this.generationConfigSnapshot = {
                    ...currentConfig,
                    api: apiUpdate,
                    generateSettings: generationUpdate,
                };
                this.generationPanelSaving = false;
            },
            error: () => {
                this.notificationService.open({
                    type: 'error',
                    title: 'Failed to save generation settings',
                    autoClose: true,
                });
                this.generationPanelSaving = false;
            }
        });
    }

    private readShowAllChatSources(): boolean {
        try {
            return localStorage.getItem(LayoutComponent.CHAT_ALL_SOURCES_KEY) === 'true';
        } catch {
            return false;
        }
    }

    private persistShowAllChatSources(value: boolean): void {
        try {
            localStorage.setItem(LayoutComponent.CHAT_ALL_SOURCES_KEY, value ? 'true' : 'false');
        } catch {
            // Ignore storage errors; the current save still updates generation settings.
        }
    }
}
