import { Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { ApiService, ModelIndexEntry } from '../../../../../core/services/api.service';
import { buildModelOptions, modelOptionLabels } from '../../../../../core/utils/model-options';
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
    originalConfig: any = {};
    /** What the router model can do, from the model index; edited in the models tab. */
    routerModelEntry: ModelIndexEntry | null = null;
    private modelIndex: ModelIndexEntry[] = [];
    private modelIndexLoaded = false;
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
        this.loadModelIndex();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            mode: ['system', Validators.required],
            activeProvider: ['ollama', Validators.required],
            maxSteps: [4, [Validators.min(1), Validators.max(12)]],
            releaseAfterUse: [true],
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
            orchestratorPrompt: [''],
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
                    orchestratorPrompt: dl.orchestratorPrompt ?? dl.orchestrator_prompt ?? '',
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

    private loadModelIndex(): void {
        this.apiService.getModelIndex$().pipe(take(1)).subscribe((entries) => {
            this.modelIndex = entries ?? [];
            this.modelIndexLoaded = true;
            this.resolveRouterModelEntry();
        });
        this.dlForm.get('providers.ollama.model')?.valueChanges.subscribe(() => this.resolveRouterModelEntry());
    }

    /** The router model's chips and the text models it can be picked from, both from the model index. */
    private resolveRouterModelEntry(): void {
        const name = String(this.dlForm.get('providers.ollama.model')?.value || '').trim();
        this.routerModelEntry = this.modelIndex.find((entry) => entry.name === name) ?? null;
        if (this.modelIndexLoaded) {
            this.ollamaModelOptions = buildModelOptions(
                this.modelIndex,
                'completion',
                name,
                modelOptionLabels((key) => this.localizationService.t(key), 'completion'),
            );
        }
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
            orchestratorPrompt: String(value.orchestratorPrompt ?? ''),
        };
    }

    /** Puts the built-in prompt back into the field; saving keeps it. */
    resetPrompt(controlPath: string, configPath: string): void {
        const control = this.dlForm.get(controlPath);
        if (!control) {
            return;
        }
        this.configService
            .getDefaultValue$(configPath)
            .pipe(take(1))
            .subscribe((value) => {
                if (typeof value !== 'string') {
                    this.notificationService.open({
                        title: 'Error',
                        type: 'error',
                        message: 'Failed to load the default prompt',
                        autoClose: true,
                    });
                    return;
                }
                control.setValue(value);
                control.markAsDirty();
            });
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
