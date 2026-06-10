import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { ApiService } from '../../../../../core/services/api.service';
import { BehaviorSubject } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';

@Component({
    selector: 'app-analyzer-settings',
    templateUrl: './analyzer-settings.component.html',
    styleUrls: ['./analyzer-settings.component.less']
})
export class AnalyzerSettingsComponent implements OnInit {
    analyzerForm: UntypedFormGroup;
    isLoading$ = new BehaviorSubject<boolean>(true);
    originalConfig: any = {};
    ollamaModelOptions: UiSelectOption[] = [
        { value: '', label: 'Модели не найдены', disabled: true },
    ];
    private readonly defaultAnalyzerSystemPrompt = `You are a cognitive filter of an AI system. Your task is to analyze incoming messages and return STRICTLY structured JSON with metadata. NEVER generate text responses for the user.`;

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private apiService: ApiService,
        private notificationService: NotificationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.analyzerForm = this.createForm();
    }

    ngOnInit(): void {
        this.loadConfig();
        this.loadOllamaModels();

        // Подписка на изменения провайдера
        this.analyzerForm.get('activeProvider')?.valueChanges.subscribe((provider: string) => {
            this.toggleFallbackControls(provider);
        });
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            enabled: [true],
            activeProvider: ['openrouter', Validators.required],
            fallbackOpenrouter: [false],
            fallbackOllama: [true],
            fallbackLlamaCpp: [false],
            releaseAfterUse: [true],
            systemPrompt: [this.defaultAnalyzerSystemPrompt, Validators.required],
            providers: this.fb.group({
                openrouter: this.createProviderGroup({}),
                ollama: this.createProviderGroup({}),
                llamaCpp: this.createLlamaCppGroup({}),
            })
        });
    }

    private createProviderGroup(providerConfig: any): UntypedFormGroup {
        return this.fb.group({
            apiKey: [providerConfig.apiKey || ''],
            model: [providerConfig.model || '', Validators.required],
            temperature: [providerConfig.temperature ?? 0.7, [Validators.min(0), Validators.max(2)]],
            maxTokens: [providerConfig.maxTokens ?? 1024, [Validators.min(1), Validators.max(4096)]],
        });
    }

    private createLlamaCppGroup(cfg: any): UntypedFormGroup {
        return this.fb.group({
            enabled: [cfg?.enabled ?? false],
            baseUrl: [cfg?.baseUrl || 'http://127.0.0.1:8080'],
            model: [cfg?.model || ''],
            temperature: [cfg?.temperature ?? 0.1, [Validators.min(0), Validators.max(2)]],
            maxTokens: [cfg?.maxTokens ?? 1024, [Validators.min(1), Validators.max(4096)]],
            requestTimeout: [cfg?.requestTimeout ?? 120, [Validators.min(1), Validators.max(600)]],
        });
    }

    private loadConfig(): void {
        this.isLoading$.next(true);

        this.configService.getConfig$().pipe(
            take(1),
            finalize(() => this.isLoading$.next(false))
        ).subscribe({
            next: (config: any) => {
                const analyzer = config?.analyzer || {};
                const providers = analyzer.providers || {};

                // Загружаем основные настройки
                this.analyzerForm.patchValue({
                    enabled: analyzer.enabled ?? true,
                    activeProvider: analyzer.activeProvider || 'openrouter',
                    fallbackOpenrouter: (analyzer.fallbackOrder || []).includes('openrouter'),
                    fallbackOllama: (analyzer.fallbackOrder || []).includes('ollama'),
                    fallbackLlamaCpp: (analyzer.fallbackOrder || []).includes('llama_cpp'),
                    releaseAfterUse: analyzer.releaseAfterUse ?? true,
                    systemPrompt: analyzer.systemPrompt || this.defaultAnalyzerSystemPrompt,
                });

                // Загружаем провайдеров в динамическую форму
                const providersGroup = this.analyzerForm.get('providers') as UntypedFormGroup;
                Object.keys(providers).forEach(providerName => {
                    const providerConfig = providers[providerName];
                    const normalizedName = providerName === 'llama_cpp' ? 'llamaCpp' : providerName;
                    const providerGroup = providersGroup.get(normalizedName) as UntypedFormGroup | null;
                    if (providerGroup) {
                        if (normalizedName === 'llamaCpp') {
                            providerGroup.patchValue({
                                enabled: providerConfig.enabled ?? false,
                                baseUrl:
                                    providerConfig.baseUrl ||
                                    providerConfig.base_url ||
                                    'http://127.0.0.1:8080',
                                model: providerConfig.model || '',
                                temperature: providerConfig.temperature ?? 0.1,
                                maxTokens:
                                    providerConfig.maxTokens ?? providerConfig.max_tokens ?? 1024,
                                requestTimeout:
                                    providerConfig.requestTimeout ??
                                    providerConfig.request_timeout ??
                                    120,
                            });
                        } else {
                            providerGroup.patchValue({
                                apiKey: providerConfig.apiKey || '',
                                model: providerConfig.model || '',
                                temperature: providerConfig.temperature ?? 0.7,
                                maxTokens: providerConfig.maxTokens ?? 1024,
                            });
                        }
                    } else if (normalizedName === 'llamaCpp') {
                        providersGroup.addControl('llamaCpp', this.createLlamaCppGroup(providerConfig));
                    } else {
                        providersGroup.addControl(normalizedName, this.createProviderGroup(providerConfig));
                    }
                });

                this.originalConfig = this.buildAnalyzerConfigFromForm();
                this.toggleFallbackControls(this.analyzerForm.get('activeProvider')?.value);
                this.ensureCurrentOllamaModelOption();
                this.cdr.markForCheck();
            },
            error: (error) => {
                console.error('Error loading analyzer config:', error);
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to load analyzer configuration',
                    autoClose: true
                });
                this.cdr.markForCheck();
            }
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
        const ctrls: Record<string, any> = {
            openrouter: this.analyzerForm.get('fallbackOpenrouter'),
            ollama: this.analyzerForm.get('fallbackOllama'),
            llama_cpp: this.analyzerForm.get('fallbackLlamaCpp'),
        };
        Object.keys(ctrls).forEach((key) => {
            const ctrl = ctrls[key];
            if (!ctrl) return;
            if (key === activeProvider) {
                ctrl.disable({ emitEvent: false });
                ctrl.setValue(false);
            } else {
                ctrl.enable({ emitEvent: false });
            }
        });
    }

    saveChanges(): void {
        const changes = this.getChanges();
        if (Object.keys(changes).length === 0) {
            return;
        }

        // Отправляем изменения в формате model (camelCase)
        this.configService.updateConfig$({ analyzer: changes }).subscribe({
            next: () => {
                this.notificationService.open({
                    title: 'Success',
                    type: 'success',
                    message: 'Analyzer settings updated successfully',
                    autoClose: true
                });
                this.originalConfig = this.buildAnalyzerConfigFromForm();
                this.analyzerForm.markAsPristine();
            },
            error: (error) => {
                console.error('Error updating analyzer settings:', error);
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to update analyzer settings',
                    autoClose: true
                });
            }
        });
    }

    private buildAnalyzerConfigFromForm(): any {
        const formValue = this.analyzerForm.getRawValue();
        const fallbackOrder: string[] = [];

        if (formValue.fallbackOpenrouter && formValue.activeProvider !== 'openrouter') {
            fallbackOrder.push('openrouter');
        }
        if (formValue.fallbackOllama && formValue.activeProvider !== 'ollama') {
            fallbackOrder.push('ollama');
        }
        if (formValue.fallbackLlamaCpp && formValue.activeProvider !== 'llama_cpp') {
            fallbackOrder.push('llama_cpp');
        }

        const providers = { ...formValue.providers };
        Object.keys(providers).forEach(providerName => {
            const provider = providers[providerName];
            // Приводим числовые поля
            provider.temperature = Number(provider.temperature);
            provider.maxTokens = Number(provider.maxTokens);
            if (providerName === 'llamaCpp') {
                provider.requestTimeout = Number(provider.requestTimeout);
            }
        });

        return {
            enabled: !!formValue.enabled,
            activeProvider: formValue.activeProvider,
            fallbackOrder: fallbackOrder,
            releaseAfterUse: !!formValue.releaseAfterUse,
            systemPrompt: String(formValue.systemPrompt || '').trim(),
            providers: providers
        };
    }

    private getChanges(): any {
        const current = this.buildAnalyzerConfigFromForm();
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

    // Геттеры для удобства доступа к контролам
    get providersForm() {
        return this.analyzerForm.get('providers') as UntypedFormGroup;
    }

    get activeProvider() {
        return this.analyzerForm.get('activeProvider')?.value;
    }

    get activeProviderOptions(): UiSelectOption[] {
        return [
            { value: 'openrouter', label: 'OpenRouter' },
            { value: 'ollama', label: 'Ollama' },
            { value: 'llama_cpp', label: 'llama.cpp' },
        ];
    }

    get isLlamaCppActive(): boolean {
        return this.activeProvider === 'llama_cpp';
    }

    get isOpenrouterActive(): boolean {
        return this.activeProvider === 'openrouter';
    }

    get isOllamaActive(): boolean {
        return this.activeProvider === 'ollama';
    }
}
