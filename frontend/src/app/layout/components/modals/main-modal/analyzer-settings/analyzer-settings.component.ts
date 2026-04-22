import { Component, OnInit } from '@angular/core';
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

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private apiService: ApiService,
        private notificationService: NotificationService
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
            activeProvider: ['openrouter', Validators.required],
            fallbackOpenrouter: [false],
            fallbackOllama: [true],
            providers: this.fb.group({})
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
                    activeProvider: analyzer.activeProvider || 'openrouter',
                    fallbackOpenrouter: (analyzer.fallbackOrder || []).includes('openrouter'),
                    fallbackOllama: (analyzer.fallbackOrder || []).includes('ollama'),
                });

                // Загружаем провайдеров в динамическую форму
                const providersGroup = this.analyzerForm.get('providers') as UntypedFormGroup;
                Object.keys(providers).forEach(providerName => {
                    const providerConfig = providers[providerName];

                    // Создаём FormGroup для провайдера в camelCase
                    const providerGroup = this.fb.group({
                        apiKey: [providerConfig.apiKey || ''],
                        model: [providerConfig.model || '', Validators.required],
                        temperature: [providerConfig.temperature || 0.7, [Validators.min(0), Validators.max(2)]],
                        maxTokens: [providerConfig.maxTokens || 1024, [Validators.min(1), Validators.max(4096)]],
                    });

                    providersGroup.addControl(providerName, providerGroup);
                });

                this.originalConfig = this.buildAnalyzerConfigFromForm();
                this.toggleFallbackControls(this.analyzerForm.get('activeProvider')?.value);
            },
            error: (error) => {
                console.error('Error loading analyzer config:', error);
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to load analyzer configuration',
                    autoClose: true
                });
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
                    return;
                }
                this.ollamaModelOptions = [{ value: '', label: 'Модели не найдены', disabled: true }];
            },
            error: () => {
                this.ollamaModelOptions = [{ value: '', label: 'Модели не найдены', disabled: true }];
            },
        });
    }

    private toggleFallbackControls(activeProvider: string): void {
        const fallbackOpenrouterCtrl = this.analyzerForm.get('fallbackOpenrouter');
        const fallbackOllamaCtrl = this.analyzerForm.get('fallbackOllama');

        if (activeProvider === 'openrouter') {
            fallbackOpenrouterCtrl?.disable({ emitEvent: false });
            fallbackOpenrouterCtrl?.setValue(false);
            fallbackOllamaCtrl?.enable({ emitEvent: false });
        } else if (activeProvider === 'ollama') {
            fallbackOllamaCtrl?.disable({ emitEvent: false });
            fallbackOllamaCtrl?.setValue(false);
            fallbackOpenrouterCtrl?.enable({ emitEvent: false });
        } else {
            fallbackOpenrouterCtrl?.enable({ emitEvent: false });
            fallbackOllamaCtrl?.enable({ emitEvent: false });
        }
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

        const providers = { ...formValue.providers };
        Object.keys(providers).forEach(providerName => {
            const provider = providers[providerName];
            // Приводим числовые поля
            provider.temperature = Number(provider.temperature);
            provider.maxTokens = Number(provider.maxTokens);
        });

        return {
            activeProvider: formValue.activeProvider,
            fallbackOrder: fallbackOrder,
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
        ];
    }
}
