import { Component } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';

@Component({
    selector: 'app-core-settings',
    templateUrl: './core-settings.component.html',
    styleUrls: ['./core-settings.component.less']
})
export class CoreSettingsComponent {
    // Модальные окна
    showDlModal = false;
    showCaModal = false;

    // Формы для настроек
    dlForm: FormGroup;
    caForm: FormGroup;

    constructor(
        private fb: FormBuilder,
        private configService: ConfigService,
        private localizationService: LocalizationService
    ) {
        this.dlForm = this.createDlForm();
        this.caForm = this.createCaForm();
        this.localizationService.init();
    }

    private createDlForm(): FormGroup {
        return this.fb.group({
            // Decision Layer настройки будут добавлены позже
        });
    }

    private createCaForm(): FormGroup {
        return this.fb.group({
            enabled: [false],
            use_api: [false],
            provider: ['ollama'],
            api_key: [''],
            api_base: [''],
            model: [''],
            local_model: ['llama3.2'],
            temperature: [0.7],
            max_tokens: [1024],
            analysis_timeout: [30],
            fallback_to_local: [true]
        });
    }

    openDlModal(): void {
        this.showDlModal = true;
    }

    closeDlModal(): void {
        this.showDlModal = false;
    }

    openCaModal(): void {
        this.loadCaConfig();
        this.showCaModal = true;
    }

    closeCaModal(): void {
        this.showCaModal = false;
    }

    private loadCaConfig(): void {
        this.configService.getConfig$().subscribe(config => {
            if (config && (config as any).cognitive_analyzer) {
                const caConfig = (config as any).cognitive_analyzer;
                this.caForm.patchValue({
                    enabled: caConfig.enabled ?? false,
                    use_api: caConfig.provider !== 'ollama' && caConfig.api_key,
                    provider: caConfig.provider ?? 'ollama',
                    api_key: caConfig.api_key ?? '',
                    api_base: caConfig.api_base ?? '',
                    model: caConfig.model ?? '',
                    local_model: caConfig.local_model ?? 'llama3.2',
                    temperature: caConfig.temperature ?? 0.7,
                    max_tokens: caConfig.max_tokens ?? 1024,
                    analysis_timeout: caConfig.analysis_timeout ?? 30,
                    fallback_to_local: caConfig.fallback_to_local ?? true
                });
            }
        });
    }

    onProviderChange(event: any): void {
        const provider = event.target.value;
        if (provider === 'openrouter') {
            // Загружаем API ключ и модель из openrouter
            this.configService.getConfig$().subscribe(config => {
                if (config && config.openrouter) {
                    this.caForm.patchValue({
                        api_key: config.openrouter.apiKey || '',
                        model: config.openrouter.model || ''
                    });
                }
            });
        }
    }

    saveCaSettings(): void {
        const formValue = this.caForm.value;

        // Определяем провайдера на основе чекбокса use_api
        const provider = formValue.use_api ? formValue.provider : 'ollama';
        const model = formValue.use_api ? formValue.model : formValue.local_model;

        const updateData = {
            cognitive_analyzer: {
                enabled: formValue.enabled,
                provider: provider,
                api_key: formValue.api_key,
                api_base: formValue.api_base,
                model: model,
                local_model: formValue.local_model,
                temperature: formValue.temperature,
                max_tokens: formValue.max_tokens,
                analysis_timeout: formValue.analysis_timeout,
                fallback_to_local: formValue.fallback_to_local
            }
        };

        this.configService.updateConfig$(updateData).subscribe({
            next: (response) => {
                console.log('Cognitive Analyzer settings updated:', response);
                this.closeCaModal();
            },
            error: (error) => {
                console.error('Error updating Cognitive Analyzer settings:', error);
            }
        });
    }

    onUseApiChange(event: any): void {
        const useApi = event.target.checked;
        if (useApi) {
            // При включении API показываем поля API
            this.caForm.get('provider')?.enable();
            this.caForm.get('api_key')?.enable();
            this.caForm.get('api_base')?.enable();
            this.caForm.get('model')?.enable();
            this.caForm.get('local_model')?.disable();
        } else {
            // При отключении API показываем поля локальной модели
            this.caForm.get('provider')?.disable();
            this.caForm.get('api_key')?.disable();
            this.caForm.get('api_base')?.disable();
            this.caForm.get('model')?.disable();
            this.caForm.get('local_model')?.enable();
        }
    }
}
