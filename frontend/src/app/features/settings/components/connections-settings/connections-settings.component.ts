import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { ConfigService } from '../../../../core/services/config.service';
import { NotificationService } from '../../../../shared/components/notification/notification.service';
import { LocalizationService } from '../../../../shared/pipes/translation/localization.service';

/**
 * Connections settings (/settings page, 0.9.3).
 *
 * Manages LLM provider endpoints and credentials under the `api` config
 * section: active provider + per-provider base URL / API key / enabled flag.
 * Generation parameters (temperature, tokens, etc.) stay in the Generation
 * tab — this tab is only about where PAI connects to.
 *
 * The PATCH body must carry the FULL api model (the mapper serializes every
 * field), so the form is merged into the api object loaded from config.
 */
@Component({
    selector: 'app-connections-settings',
    templateUrl: './connections-settings.component.html',
    styleUrls: ['./connections-settings.component.less'],
})
export class ConnectionsSettingsComponent implements OnInit {
    form: UntypedFormGroup;
    isLoading$ = new BehaviorSubject<boolean>(true);
    isSaving = false;

    readonly providerOptions = [
        { label: 'Ollama', value: 'ollama' },
        { label: 'llama.cpp', value: 'llama_cpp' },
        { label: 'OpenRouter', value: 'openrouter' },
        { label: 'Transformers', value: 'transformers' },
    ];

    private apiModel: any = null;
    private originalSnapshot = '';

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.form = this.fb.group({
            activeProvider: ['ollama'],
            ollama: this.fb.group({
                baseUrl: ['http://localhost:11434'],
                model: [''],
            }),
            llamaCpp: this.fb.group({
                enabled: [false],
                baseUrl: ['http://127.0.0.1:8080'],
                model: [''],
            }),
            openrouter: this.fb.group({
                baseUrl: ['https://openrouter.ai/api/v1'],
                apiKey: [''],
                model: [''],
            }),
            transformers: this.fb.group({
                model: [''],
            }),
        });
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.loadConfig();
    }

    t(key: string): string {
        return this.localizationService.t(key);
    }

    hasChanges(): boolean {
        return JSON.stringify(this.form.getRawValue()) !== this.originalSnapshot;
    }

    private loadConfig(): void {
        this.isLoading$.next(true);
        this.configService
            .getConfig$()
            .pipe(take(1), finalize(() => this.isLoading$.next(false)))
            .subscribe({
                next: (config: any) => {
                    if (config?.api) {
                        this.apiModel = JSON.parse(JSON.stringify(config.api));
                        this.patchFromApi(this.apiModel);
                    }
                    this.originalSnapshot = JSON.stringify(this.form.getRawValue());
                    this.cdr.markForCheck();
                },
                error: () => {
                    this.notificationService.open({
                        title: 'Error',
                        type: 'error',
                        message: this.t('settingsPage.connections.loadError'),
                        autoClose: true,
                    });
                },
            });
    }

    private patchFromApi(api: any): void {
        const providers = api.providers || {};
        this.form.patchValue({
            activeProvider: api.activeProvider || 'ollama',
            ollama: {
                baseUrl: providers.ollama?.baseUrl ?? 'http://localhost:11434',
                model: providers.ollama?.model ?? '',
            },
            llamaCpp: {
                enabled: providers.llama_cpp?.enabled ?? false,
                baseUrl: providers.llama_cpp?.baseUrl ?? 'http://127.0.0.1:8080',
                model: providers.llama_cpp?.model ?? '',
            },
            openrouter: {
                baseUrl: providers.openrouter?.baseUrl ?? 'https://openrouter.ai/api/v1',
                apiKey: providers.openrouter?.apiKey ?? '',
                model: providers.openrouter?.model ?? '',
            },
            transformers: {
                model: providers.transformers?.model ?? '',
            },
        });
    }

    saveChanges(): void {
        if (!this.apiModel || !this.hasChanges() || this.isSaving) {
            return;
        }
        const v = this.form.getRawValue();
        const api = JSON.parse(JSON.stringify(this.apiModel));
        api.providers = api.providers || {};

        api.activeProvider = v.activeProvider;
        api.providers.ollama = {
            ...(api.providers.ollama || {}),
            baseUrl: v.ollama.baseUrl,
            model: v.ollama.model,
        };
        api.providers.llama_cpp = {
            ...(api.providers.llama_cpp || {}),
            enabled: v.llamaCpp.enabled,
            baseUrl: v.llamaCpp.baseUrl,
            model: v.llamaCpp.model,
        };
        api.providers.openrouter = {
            ...(api.providers.openrouter || {}),
            baseUrl: v.openrouter.baseUrl,
            apiKey: v.openrouter.apiKey,
            model: v.openrouter.model,
        };
        api.providers.transformers = {
            ...(api.providers.transformers || {}),
            model: v.transformers.model,
        };
        // The mapper takes the active provider's model from api.model — keep
        // them in sync so switching providers doesn't resurrect a stale model.
        const activeModel = api.providers[api.activeProvider]?.model;
        if (activeModel) {
            api.model = activeModel;
        }

        this.isSaving = true;
        this.configService
            .updateConfig$({ api })
            .pipe(finalize(() => {
                this.isSaving = false;
                this.cdr.markForCheck();
            }))
            .subscribe({
                next: () => {
                    this.apiModel = api;
                    this.originalSnapshot = JSON.stringify(this.form.getRawValue());
                    this.notificationService.open({
                        title: 'Success',
                        type: 'success',
                        message: this.t('settingsPage.connections.saved'),
                        autoClose: true,
                    });
                },
                error: () => {
                    this.notificationService.open({
                        title: 'Error',
                        type: 'error',
                        message: this.t('settingsPage.connections.saveError'),
                        autoClose: true,
                    });
                },
            });
    }
}
