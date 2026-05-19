import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { ApiService } from '../../../../../core/services/api.service';
import { ConfigService } from '../../../../../core/services/config.service';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';

@Component({
    selector: 'app-moral-settings',
    templateUrl: './moral-settings.component.html',
    styleUrls: ['./moral-settings.component.less']
})
export class MoralSettingsComponent implements OnInit {
    moralForm: UntypedFormGroup;
    isLoading$ = new BehaviorSubject<boolean>(true);
    originalConfig: any = {};
    ollamaModelOptions: UiSelectOption[] = [
        { value: '', label: 'Модели не найдены', disabled: true },
    ];
    private readonly defaultMoralSystemPrompt = `You are the MoralMatrix governor. Your output augments an AI companion's emotional behaviour. Receive the current evaluation payload (JSON) and respond with STRICT JSON containing guidance.`;

    constructor(
        private fb: UntypedFormBuilder,
        private apiService: ApiService,
        private configService: ConfigService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.moralForm = this.createForm();
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.loadConfig();
        this.loadOllamaModels();
        this.moralForm.get('activeProvider')?.valueChanges.subscribe((provider: string) => {
            const normalized = this.normalizeProvider(provider);
            if (normalized !== provider) {
                this.moralForm.get('activeProvider')?.setValue(normalized, { emitEvent: false });
            }
            this.toggleFallbackControls(normalized);
        });
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            enabled: [true],
            activeProvider: ['ollama', Validators.required],
            fallbackHeuristic: [true],
            fallbackOllama: [true],
            fallbackOpenrouter: [false],
            releaseAfterUse: [true],
            systemPrompt: [this.defaultMoralSystemPrompt, Validators.required],
            providers: this.fb.group({
                ollama: this.fb.group({
                    model: ['', Validators.required],
                    temperature: [0.6, [Validators.min(0), Validators.max(2)]],
                    maxTokens: [512, [Validators.min(1), Validators.max(4096)]],
                    thinking: [false],
                }),
                openrouter: this.fb.group({
                    apiKey: [''],
                    model: ['', Validators.required],
                    temperature: [0.6, [Validators.min(0), Validators.max(2)]],
                    maxTokens: [512, [Validators.min(1), Validators.max(4096)]],
                }),
            }),
        });
    }

    private loadConfig(): void {
        this.isLoading$.next(true);

        this.configService
            .getConfig$()
            .pipe(
                take(1),
                finalize(() => this.isLoading$.next(false))
            )
            .subscribe({
                next: (config: any) => {
                    const moral = config?.moral || {};
                    const providers = moral.providers || {};

                    this.moralForm.patchValue({
                        enabled: moral.enabled ?? true,
                        activeProvider: this.normalizeProvider(moral.activeProvider || 'ollama'),
                        fallbackHeuristic: (moral.fallbackOrder || []).includes('heuristic'),
                        fallbackOllama: (moral.fallbackOrder || []).includes('ollama'),
                        fallbackOpenrouter: (moral.fallbackOrder || []).includes('openrouter'),
                        releaseAfterUse: moral.releaseAfterUse ?? true,
                        systemPrompt: moral.systemPrompt || this.defaultMoralSystemPrompt,
                    });

                    const providersGroup = this.moralForm.get('providers') as UntypedFormGroup;
                    const ollamaGroup = providersGroup.get('ollama') as UntypedFormGroup;
                    const openrouterGroup = providersGroup.get('openrouter') as UntypedFormGroup;

                    if (providers.ollama) {
                        ollamaGroup.patchValue({
                            model: providers.ollama.model || '',
                            temperature: providers.ollama.temperature ?? 0.6,
                            maxTokens: providers.ollama.maxTokens ?? providers.ollama.max_tokens ?? 512,
                            thinking: providers.ollama.thinking ?? false,
                        });
                    }

                    if (providers.openrouter) {
                        openrouterGroup.patchValue({
                            apiKey: providers.openrouter.apiKey || providers.openrouter.api_key || '',
                            model: providers.openrouter.model || '',
                            temperature: providers.openrouter.temperature ?? 0.6,
                            maxTokens: providers.openrouter.maxTokens ?? providers.openrouter.max_tokens ?? 512,
                        });
                    }

                    this.originalConfig = this.buildMoralConfigFromForm();
                    this.toggleFallbackControls(this.activeProvider);
                    this.ensureCurrentOllamaModelOption();
                    this.cdr.markForCheck();
                },
                error: (error) => {
                    console.error('Error loading moral config:', error);
                    this.notificationService.open({
                        title: 'Error',
                        type: 'error',
                        message: 'Failed to load Moral Matrix configuration',
                        autoClose: true,
                    });
                    this.cdr.markForCheck();
                },
            });
    }

    private loadOllamaModels(): void {
        this.apiService.getOllamaModels$().pipe(take(1)).subscribe({
            next: (models: string[]) => {
                const cleaned = (Array.isArray(models) ? models : [])
                    .map((item) => String(item || '').trim())
                    .filter((item) => item.length > 0);
                if (cleaned.length > 0) {
                    this.ollamaModelOptions = cleaned.map((model) => ({ value: model, label: model }));
                    this.ensureCurrentOllamaModelOption();
                    this.cdr.markForCheck();
                    return;
                }
                this.ollamaModelOptions = [{ value: '', label: 'Модели не найдены', disabled: true }];
                this.ensureCurrentOllamaModelOption();
                this.cdr.markForCheck();
            },
            error: () => {
                this.ollamaModelOptions = [{ value: '', label: 'Модели не найдены', disabled: true }];
                this.ensureCurrentOllamaModelOption();
                this.cdr.markForCheck();
            },
        });
    }

    private ensureCurrentOllamaModelOption(): void {
        const current = String(this.providersForm.get('ollama.model')?.value || '').trim();
        if (!current || this.ollamaModelOptions.some((item) => item.value === current)) {
            return;
        }
        this.ollamaModelOptions = [{ value: current, label: current }, ...this.ollamaModelOptions];
    }

    private toggleFallbackControls(activeProvider: string): void {
        const provider = this.normalizeProvider(activeProvider);
        const fallbackHeuristicCtrl = this.moralForm.get('fallbackHeuristic');
        const fallbackOllamaCtrl = this.moralForm.get('fallbackOllama');
        const fallbackOpenrouterCtrl = this.moralForm.get('fallbackOpenrouter');

        if (provider === 'heuristic') {
            fallbackHeuristicCtrl?.disable({ emitEvent: false });
            fallbackHeuristicCtrl?.setValue(false, { emitEvent: false });
            fallbackOllamaCtrl?.enable({ emitEvent: false });
            fallbackOpenrouterCtrl?.enable({ emitEvent: false });
        } else if (provider === 'ollama') {
            fallbackOllamaCtrl?.disable({ emitEvent: false });
            fallbackOllamaCtrl?.setValue(false, { emitEvent: false });
            fallbackHeuristicCtrl?.enable({ emitEvent: false });
            fallbackOpenrouterCtrl?.enable({ emitEvent: false });
        } else if (provider === 'openrouter') {
            fallbackOpenrouterCtrl?.disable({ emitEvent: false });
            fallbackOpenrouterCtrl?.setValue(false, { emitEvent: false });
            fallbackHeuristicCtrl?.enable({ emitEvent: false });
            fallbackOllamaCtrl?.enable({ emitEvent: false });
        } else {
            fallbackHeuristicCtrl?.enable({ emitEvent: false });
            fallbackOllamaCtrl?.enable({ emitEvent: false });
            fallbackOpenrouterCtrl?.enable({ emitEvent: false });
        }
    }

    saveChanges(): void {
        const changes = this.getChanges();
        if (Object.keys(changes).length === 0) {
            return;
        }

        this.configService.updateConfig$({ moral: changes }).subscribe({
            next: () => {
                this.notificationService.open({
                    title: 'Success',
                    type: 'success',
                    message: 'Moral Matrix settings updated successfully',
                    autoClose: true,
                });
                this.originalConfig = this.buildMoralConfigFromForm();
                this.moralForm.markAsPristine();
            },
            error: (error) => {
                console.error('Error updating moral settings:', error);
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to update Moral Matrix settings',
                    autoClose: true,
                });
            },
        });
    }

    private buildMoralConfigFromForm(): any {
        const formValue = this.moralForm.getRawValue();
        const activeProvider = this.normalizeProvider(formValue.activeProvider);
        const fallbackOrder: string[] = [];

        if (formValue.fallbackHeuristic && activeProvider !== 'heuristic') {
            fallbackOrder.push('heuristic');
        }
        if (formValue.fallbackOllama && activeProvider !== 'ollama') {
            fallbackOrder.push('ollama');
        }
        if (formValue.fallbackOpenrouter && activeProvider !== 'openrouter') {
            fallbackOrder.push('openrouter');
        }

        const providers = {
            heuristic: {},
            ollama: {
                model: formValue.providers.ollama.model,
                temperature: Number(formValue.providers.ollama.temperature),
                maxTokens: Number(formValue.providers.ollama.maxTokens),
                thinking: Boolean(formValue.providers.ollama.thinking),
            },
            openrouter: {
                apiKey: formValue.providers.openrouter.apiKey,
                model: formValue.providers.openrouter.model,
                temperature: Number(formValue.providers.openrouter.temperature),
                maxTokens: Number(formValue.providers.openrouter.maxTokens),
            },
        };

        return {
            enabled: formValue.enabled,
            activeProvider,
            fallbackOrder,
            releaseAfterUse: !!formValue.releaseAfterUse,
            systemPrompt: String(formValue.systemPrompt || '').trim(),
            providers,
        };
    }

    private getChanges(): any {
        const current = this.buildMoralConfigFromForm();
        const original = this.originalConfig || {};
        return this.deepDiff(original, current) || {};
    }

    private deepDiff(original: any, current: any): any {
        if (Array.isArray(current)) {
            const originalArray = Array.isArray(original) ? original : [];
            if (JSON.stringify(current) === JSON.stringify(originalArray)) {
                return undefined;
            }
            return current;
        }

        if (current !== null && typeof current === 'object') {
            const diff: Record<string, any> = {};

            Object.keys(current).forEach((key) => {
                const value = this.deepDiff(original ? original[key] : undefined, current[key]);
                if (value !== undefined) {
                    diff[key] = value;
                }
            });

            return Object.keys(diff).length > 0 ? diff : undefined;
        }

        if (current !== original) {
            return current;
        }

        return undefined;
    }

    hasChanges(): boolean {
        return Object.keys(this.getChanges()).length > 0;
    }

    get providersForm(): UntypedFormGroup {
        return this.moralForm.get('providers') as UntypedFormGroup;
    }

    get activeProvider(): string {
        return this.normalizeProvider(this.moralForm.get('activeProvider')?.value);
    }

    get isOllamaActive(): boolean {
        return this.activeProvider === 'ollama';
    }

    get isOpenrouterActive(): boolean {
        return this.activeProvider === 'openrouter';
    }

    get activeProviderOptions(): UiSelectOption[] {
        return [
            { value: 'ollama', label: 'Ollama' },
            { value: 'openrouter', label: 'OpenRouter' },
            { value: 'heuristic', label: this.localizationService.t('moralSettings.heuristicProvider') },
        ];
    }

    private normalizeProvider(value: any): string {
        return String(value || '').trim().toLowerCase();
    }
}
