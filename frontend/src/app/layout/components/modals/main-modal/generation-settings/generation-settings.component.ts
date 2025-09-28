import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { ApiService } from '../../../../../core/services/api.service';
import { GenerationPreset } from '../../../../../core/models/generation-preset.model';
import { combineLatest, BehaviorSubject } from 'rxjs';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { tap, finalize } from 'rxjs/operators';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';

@Component({
    selector: 'app-generation-settings',
    templateUrl: './generation-settings.component.html',
    styleUrls: ['./generation-settings.component.less']
})
export class GenerationSettingsComponent implements OnInit {
    @ViewChild('tokenSlider') tokenSliderRef!: ElementRef<HTMLInputElement>;
    @ViewChild('tokenInput') tokenInputRef!: ElementRef<HTMLInputElement>;

    generationForm: FormGroup;
    generationSettingsForm: FormGroup;
    originalConfig: any;
    presets: GenerationPreset[] = [];
    selectedPresetName: string = 'default';
    availableModels: string[] = [];
    dropdownOpen: boolean = false;
    selectedModel = '';
    isLoading$ = new BehaviorSubject<boolean>(true);

    constructor(
        private fb: FormBuilder,
        private configService: ConfigService,
        private apiService: ApiService,
        private localizationService: LocalizationService,
        private notificationService: NotificationService,
    ) {
        this.generationForm = this.createMainForm();
        this.generationSettingsForm = this.createGenerationSettingsForm();
    }

    ngOnInit(): void {
        this.loadConfigAndPresets();
        this.setupTokenLimitSync();
        this.localizationService.init();
    }

    private createMainForm(): FormGroup {
        return this.fb.group({
            apiType: ['Ollama'],
            modelName: ['gpt-oss:20b'],
            visualModel: ['apple/FastVLM-1.5B'],
            tokenLimit: [2048],
            messagePairLimit: [10],
            streaming: [true]
        });
    }

    private createGenerationSettingsForm(): FormGroup {
        return this.fb.group({
            name: [''],
            description: [''],
            temperature: [1.2],
            topP: [0.9],
            topK: [70],
            minP: [0.05],
            repeatPenalty: [1.2],
            numPredict: [2048],
            stop: [[]]
        });
    }

    private loadConfigAndPresets(): void {
        combineLatest([
            this.configService.getConfig$(),
            this.configService.getGenerationPresets$(),
            this.apiService.getOllamaModels$()
        ]).pipe(
            tap(() => this.isLoading$.next(true)),
            finalize(() => this.isLoading$.next(false))
        ).subscribe(([config, presets, models]) => {
            // Load config
            if (config) {
                this.originalConfig = {
                    api: { ...config.api },
                    generateSettings: { ...config.generateSettings }
                };

                this.generationForm.patchValue({
                    apiType: config.api.type,
                    modelName: config.api.model,
                    visualModel: config.api.visualModel,
                    tokenLimit: config.api.tokenLimit,
                    messagePairLimit: config.api.messagePairLimit,
                    streaming: config.api.streaming
                });

                this.generationSettingsForm.patchValue(config.generateSettings);
                this.selectedModel = config.api.model;
            }

            // Load presets
            this.presets = presets;
            const activePreset = presets.find(p => p.name === this.selectedPresetName) || presets[0];
            if (activePreset) {
                this.generationSettingsForm.patchValue(activePreset);
                this.selectedPresetName = activePreset.name;
            }

            // Load models
            this.availableModels = models;
        });
    }

    private setupTokenLimitSync(): void {
        const tokenLimitControl = this.generationForm.get('tokenLimit');

        tokenLimitControl?.valueChanges.subscribe(value => {
            if (!value) return;

            if (this.tokenSliderRef?.nativeElement) {
                this.tokenSliderRef.nativeElement.value = value.toString();
            }

            if (this.tokenInputRef?.nativeElement) {
                this.tokenInputRef.nativeElement.value = value.toString();
            }
        });
    }

    toggleDropdown() {
        this.dropdownOpen = !this.dropdownOpen;
    }

    selectModel(model: string) {
        this.selectedModel = model;
        this.dropdownOpen = false;
        this.generationForm.get('modelName')?.setValue(model);
    }

    applyPreset(presetName: string) {
        const preset = this.presets.find(p => p.name === presetName);
        if (preset) {
            this.generationSettingsForm.patchValue(preset);
            this.selectedPresetName = presetName;
        }
    }

    saveOrUpdatePreset() {
        const current = this.generationSettingsForm.value;
        this.configService.saveGenerationPreset$(current).subscribe();
    }

    saveChanges(): void {
        const mainChanges = this.getMainChanges();
        const generationChanges = this.getGenerationChanges();

        const updateData: any = {};

        if (Object.keys(mainChanges).length > 0) {
            updateData.api = {
                type: mainChanges.apiType,
                model: mainChanges.modelName,
                visualModel: mainChanges.visualModel,
                tokenLimit: mainChanges.tokenLimit,
                messagePairLimit: mainChanges.messagePairLimit,
                streaming: mainChanges.streaming
            };
        }

        if (Object.keys(generationChanges).length > 0) {
            updateData.generateSettings = generationChanges;
        }

        if (Object.keys(updateData).length > 0) {
            this.configService.updateConfig$(updateData).subscribe({
                next: (response) => {
                    this.notificationService.open({
                        title: 'Generation settings updated',
                        type: 'success',
                        autoClose: false
                    });
                    console.log('Generation settings updated:', response);
                    this.originalConfig = {
                        api: { ...this.generationForm.value },
                        generateSettings: { ...this.generationSettingsForm.value }
                    };
                },
                error: (error) => {
                    this.notificationService.open({
                        title: 'Error updating generation settings',
                        type: 'error',
                        autoClose: false,
                        
                    });
                    console.error('Error updating generation settings:', error);
                }
            });
        }
    }

    onPresetChange(event: Event): void {
        const target = event.target as HTMLSelectElement;
        this.applyPreset(target.value);
    }

    private getMainChanges(): any {
        const current = this.generationForm.value;
        const changes: any = {};

        Object.keys(current).forEach(key => {
            if (current[key] !== this.originalConfig?.api?.[key]) {
                changes[key] = current[key];
            }
        });

        return changes;
    }

    private getGenerationChanges(): any {
        const current = this.generationSettingsForm.value;
        const changes: any = {};

        Object.keys(current).forEach(key => {
            if (current[key] !== this.originalConfig?.generateSettings?.[key]) {
                changes[key] = current[key];
            }
        });

        return changes;
    }

    hasChanges(): boolean {
        const mainChanges = this.getMainChanges();
        const generationChanges = this.getGenerationChanges();
        return Object.keys(mainChanges).length > 0 || Object.keys(generationChanges).length > 0;
    }
}
