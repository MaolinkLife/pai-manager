import { Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { ApiService } from '../../../../../core/services/api.service';
import { ConfigService } from '../../../../../core/services/config.service';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';

@Component({
    selector: 'app-core-settings',
    templateUrl: './core-settings.component.html',
    styleUrls: ['./core-settings.component.less']
})
export class CoreSettingsComponent implements OnInit {
    showDlModal = false;
    showInstructorModal = false;
    dlForm: UntypedFormGroup;
    isLoading$ = new BehaviorSubject<boolean>(true);
    isChecking$ = new BehaviorSubject<boolean>(false);
    originalConfig: any = {};
    capabilityDetails: Record<string, any> | null = null;
    ollamaModelOptions: UiSelectOption[] = [
        { value: '', label: 'Модели не найдены', disabled: true },
    ];

    constructor(
        private fb: UntypedFormBuilder,
        private localizationService: LocalizationService,
        private configService: ConfigService,
        private apiService: ApiService,
        private notificationService: NotificationService
    ) {
        this.dlForm = this.createForm();
        this.localizationService.init();
    }

    ngOnInit(): void {
        this.loadConfig();
        this.loadOllamaModels();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            mode: ['system', Validators.required],
            activeProvider: ['ollama', Validators.required],
            maxSteps: [4, [Validators.min(1), Validators.max(12)]],
            releaseAfterUse: [true],
            capabilities: this.fb.group({
                tool: [false],
                vision: [false],
                thinking: [false],
            }),
            providers: this.fb.group({
                ollama: this.fb.group({
                    model: ['llama3.2', Validators.required],
                    temperature: [0.2, [Validators.min(0), Validators.max(2)]],
                    maxTokens: [512, [Validators.min(1), Validators.max(4096)]],
                }),
            }),
            instructor: this.fb.group({
                buildSchema: [
                    '[CORE]\n{core}\n\n[RULES]\n{rules}\n\n[CONTEXT]\n{context}\n\n[MEMORY]\n{memory}\n\n[PERCEPTION]\n{perception}\n\n[SELF_STATE]\n{self_state}\n\n[OUTPUT]\nWrite the final user-facing reply using only relevant context.',
                ],
                includeDatetime: [true],
                includeGeolocation: [false],
                excludeDisabledModules: [true],
            }),
        });
    }

    private loadConfig(): void {
        this.isLoading$.next(true);
        this.configService.getConfig$().pipe(
            take(1),
            finalize(() => this.isLoading$.next(false))
        ).subscribe({
            next: (config) => {
                const dl: any = config?.decisionLayer || {};
                this.dlForm.patchValue({
                    mode: dl.mode || 'system',
                    activeProvider: dl.activeProvider || 'ollama',
                    maxSteps: dl.maxSteps || 4,
                    releaseAfterUse: dl.releaseAfterUse ?? true,
                    capabilities: {
                        tool: !!dl.capabilities?.tool,
                        vision: !!dl.capabilities?.vision,
                        thinking: !!dl.capabilities?.thinking,
                    },
                    providers: {
                        ollama: {
                            model: dl.providers?.ollama?.model || config?.api?.providers?.ollama?.model || config?.api?.model || 'llama3.2',
                            temperature: dl.providers?.ollama?.temperature ?? 0.2,
                            maxTokens: dl.providers?.ollama?.maxTokens ?? 512,
                        },
                    },
                    instructor: {
                        buildSchema: dl.instructor?.buildSchema || dl.instructor?.build_schema || this.dlForm.get('instructor.buildSchema')?.value,
                        includeDatetime: dl.instructor?.includeDatetime ?? dl.instructor?.include_datetime ?? true,
                        includeGeolocation: dl.instructor?.includeGeolocation ?? dl.instructor?.include_geolocation ?? false,
                        excludeDisabledModules:
                            dl.instructor?.excludeDisabledModules ?? dl.instructor?.exclude_disabled_modules ?? true,
                    },
                });
                this.originalConfig = this.buildDecisionLayerConfigFromForm();
            },
            error: () => {
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to load Decision Layer settings',
                    autoClose: true,
                });
            },
        });
    }

    private loadOllamaModels(): void {
        this.apiService.getOllamaModels$().pipe(take(1)).subscribe({
            next: (models: string[]) => {
                const cleaned = (Array.isArray(models) ? models : [])
                    .map((item) => String(item || '').trim())
                    .filter((item) => item.length > 0);
                this.ollamaModelOptions = cleaned.length
                    ? cleaned.map((model) => ({ value: model, label: model }))
                    : [{ value: '', label: 'Модели не найдены', disabled: true }];
            },
            error: () => {
                this.ollamaModelOptions = [{ value: '', label: 'Модели не найдены', disabled: true }];
            },
        });
    }

    openDlModal(): void {
        this.showDlModal = true;
    }

    closeDlModal(): void {
        this.showDlModal = false;
    }

    openInstructorModal(): void {
        this.showInstructorModal = true;
    }

    closeInstructorModal(): void {
        this.showInstructorModal = false;
    }

    checkCapabilities(): void {
        const model = this.dlForm.get('providers.ollama.model')?.value;
        if (!model) {
            return;
        }
        this.isChecking$.next(true);
        this.apiService.checkOllamaCapabilities$(model).pipe(
            take(1),
            finalize(() => this.isChecking$.next(false))
        ).subscribe((result) => {
            if (!result) {
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to check Ollama model capabilities',
                    autoClose: true,
                });
                return;
            }

            this.dlForm.patchValue({
                capabilities: {
                    tool: !!result.capabilities.tool,
                    vision: !!result.capabilities.vision,
                    thinking: !!result.capabilities.thinking,
                },
            });
            this.capabilityDetails = result.details || null;
            this.notificationService.open({
                title: 'OK',
                type: 'success',
                message: 'Model capabilities checked',
                autoClose: true,
            });
        });
    }

    saveChanges(): void {
        const changes = this.getChanges();
        if (!Object.keys(changes).length) {
            return;
        }
        this.configService.updateConfig$({ decisionLayer: changes }).subscribe({
            next: () => {
                this.originalConfig = this.buildDecisionLayerConfigFromForm();
                this.dlForm.markAsPristine();
                this.notificationService.open({
                    title: 'Success',
                    type: 'success',
                    message: 'Decision Layer settings updated',
                    autoClose: true,
                });
                this.closeDlModal();
                this.closeInstructorModal();
            },
            error: () => {
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to update Decision Layer settings',
                    autoClose: true,
                });
            },
        });
    }

    private buildDecisionLayerConfigFromForm(): any {
        const value = this.dlForm.getRawValue();
        return {
            mode: value.mode,
            activeProvider: value.activeProvider,
            maxSteps: Number(value.maxSteps),
            releaseAfterUse: !!value.releaseAfterUse,
            capabilities: {
                tool: !!value.capabilities.tool,
                vision: !!value.capabilities.vision,
                thinking: !!value.capabilities.thinking,
            },
            providers: {
                ollama: {
                    model: value.providers.ollama.model,
                    temperature: Number(value.providers.ollama.temperature),
                    maxTokens: Number(value.providers.ollama.maxTokens),
                },
            },
            instructor: {
                buildSchema: String(value.instructor.buildSchema || ''),
                includeDatetime: !!value.instructor.includeDatetime,
                includeGeolocation: !!value.instructor.includeGeolocation,
                excludeDisabledModules: !!value.instructor.excludeDisabledModules,
            },
        };
    }

    private getChanges(): any {
        const current = this.buildDecisionLayerConfigFromForm();
        return this.deepDiff(this.originalConfig || {}, current) || {};
    }

    private deepDiff(original: any, current: any): any {
        if (current !== null && typeof current === 'object' && !Array.isArray(current)) {
            const diff: Record<string, any> = {};
            Object.keys(current).forEach((key) => {
                const value = this.deepDiff(original ? original[key] : undefined, current[key]);
                if (value !== undefined) {
                    diff[key] = value;
                }
            });
            return Object.keys(diff).length ? diff : undefined;
        }
        return current !== original ? current : undefined;
    }

    hasChanges(): boolean {
        return Object.keys(this.getChanges()).length > 0;
    }

    get modeOptions(): UiSelectOption[] {
        return [
            { value: 'system', label: 'Системный' },
            { value: 'llm', label: 'Интеллектуальный' },
        ];
    }

    get providerOptions(): UiSelectOption[] {
        return [{ value: 'ollama', label: 'Ollama' }];
    }
}
