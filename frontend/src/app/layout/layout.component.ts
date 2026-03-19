import { Component, OnInit } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { ModalService } from '../shared/components/modal/modal.service';
import { MemoryModalComponent } from './components/modals/memory-modal/memory-modal.component';
import { MOCK_LOREBOOK } from '../shared/mock/lorebook-mock';
import { MainModalComponent } from './components/modals/main-modal/main-modal.component';
import { NotificationService } from '../shared/components/notification/notification.service';
import { ThemeService } from '../core/services/theme.service';
import { ConfigService } from '../core/services/config.service';
import { ApiService } from '../core/services/api.service';
import { ProjectConfig } from '../core/models/project-config.model';
import { filter } from 'rxjs/operators';
import { UiFeatureFlagsService } from '../core/services/ui-feature-flags.service';
import { AuthService } from '../core/services/auth.service';
import { AuthUser } from '../core/models/auth.model';

@Component({
    selector: 'app-layout',
    templateUrl: './layout.component.html',
    styleUrls: ['./layout.component.less']
})
export class LayoutComponent implements OnInit {
    currentTheme: 'dark' | 'light' = 'dark';
    isChatRoute = false;
    generationPanelOpen = false;
    entityPanelOpen = false;
    generationPanelLoading = false;
    generationPanelSaving = false;
    generationProvider = 'ollama';
    generationModel = '';
    generationModels: string[] = [];
    generationTemperature = 1.0;
    generationTopP = 0.9;
    generationTopK = 40;
    generationMaxTokens = 1024;
    uiFlags = { audit: false, diary: false, tasks: false };
    profileMenuOpen = false;
    currentUser: AuthUser | null = null;
    anonymousMode = false;
    private generationConfigSnapshot: ProjectConfig | null = null;

    constructor(
        private modalService: ModalService,
        private notificationService: NotificationService,
        private theme: ThemeService,
        private configService: ConfigService,
        private apiService: ApiService,
        private authService: AuthService,
        private uiFeatureFlags: UiFeatureFlagsService,
        private router: Router
    ) { }

    ngOnInit(): void {
        this.currentTheme = this.theme.getTheme();
        this.theme.initTheme();
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

    toggleTheme() {
        this.theme.toggleTheme();
        this.currentTheme = this.theme.getTheme();
    }

    memoryClick() {
        this.modalService.open(MainModalComponent, {
            title: 'Settings',
            data: { entries: [] }
        }).afterClosed$.subscribe(updated => {
            console.log('Сохранено:', updated);
        });
    }

    openSettingsModal() {
        this.modalService.open(MainModalComponent, {
            title: 'Settings',
            data: { entries: [] }
        }).afterClosed$.subscribe(updated => {
            console.log('Сохранено:', updated);
        });
    }

    toggleGenerationPanel(): void {
        this.generationPanelOpen = !this.generationPanelOpen;
        if (this.generationPanelOpen) {
            this.loadQuickGenerationSettings();
        }
    }

    closeGenerationPanel(): void {
        this.generationPanelOpen = false;
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

                if (provider === 'ollama') {
                    this.apiService.getOllamaModels$().subscribe({
                        next: (models) => {
                            const modelSet = new Set(models || []);
                            if (this.generationModel) {
                                modelSet.add(this.generationModel);
                            }
                            this.generationModels = Array.from(modelSet);
                            this.generationPanelLoading = false;
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
            },
            error: () => {
                this.generationPanelLoading = false;
            }
        });
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
            providers,
        };

        const generationUpdate = {
            ...currentConfig.generateSettings,
            temperature: this.generationTemperature,
            topP: this.generationTopP,
            topK: this.generationTopK,
            numPredict: this.generationMaxTokens,
        };

        this.generationPanelSaving = true;
        this.configService.updateConfig$({
            api: apiUpdate,
            generateSettings: generationUpdate,
        }).subscribe({
            next: () => {
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
}
