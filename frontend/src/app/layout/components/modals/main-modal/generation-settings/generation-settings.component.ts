import { Component, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { ApiService } from '../../../../../core/services/api.service';
import { GenerationPreset } from '../../../../../core/models/generation-preset.model';
import { combineLatest, BehaviorSubject, Subject } from 'rxjs';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { tap, finalize, takeUntil, distinctUntilChanged } from 'rxjs/operators';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';

@Component({
    selector: 'app-generation-settings',
    templateUrl: './generation-settings.component.html',
    styleUrls: ['./generation-settings.component.less']
})
export class GenerationSettingsComponent implements OnInit, OnDestroy {
    private readonly builtInProviderDefaults: Record<string, any> = {
        ollama: {
            model: 'llama3.2',
            temperature: 0.85,
            maxTokens: 2048,
            streaming: true,
            baseUrl: 'http://localhost:11434',
        },
        openrouter: {
            apiKey: '',
            model: '',
            temperature: 0.85,
            maxTokens: 2048,
            baseUrl: 'https://openrouter.ai/api/v1',
        },
        transformers: {
            model: '',
            temperature: 0.85,
            maxTokens: 2048,
            streaming: true,
            device_map: 'auto',
            torch_dtype: 'auto',
            trust_remote_code: true,
            low_cpu_mem_usage: true,
            do_sample: true,
            top_p: 0.9,
            top_k: 50,
            repetition_penalty: 1.1,
            keep_loaded: true,
            source: 'huggingface',
        },
    };

    generationForm: UntypedFormGroup;
    generationSettingsForm: UntypedFormGroup;
    originalConfig: any;
    presets: GenerationPreset[] = [];
    selectedPresetName: string = 'default';
    availableModels: string[] = [];
    dropdownOpen: boolean = false;
    selectedModel = '';
    isLoading$ = new BehaviorSubject<boolean>(true);
    providerKeys: string[] = [];
    apiTypeOptions: string[] = [];
    visualModelDropdownOpen = false;
    visualModelManualOptions: string[] = [];
    private ollamaModels: string[] = [];
    private destroy$ = new Subject<void>();
    private readonly tokenLimitMin = 512;
    private readonly tokenLimitMax = 131072;
    private readonly generationDefaults = {
        name: 'Default',
        description: 'Basic generation parameters',
        temperature: 0.85,
        topP: 0.9,
        topK: 50,
        minP: 0.05,
        repeatPenalty: 1.2,
        numPredict: 2048,
        normalizeMessages: false,
        stop: null as string[] | null,
    };

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private apiService: ApiService,
        private localizationService: LocalizationService,
        private notificationService: NotificationService,
    ) {
        this.generationForm = this.createMainForm();
        this.generationSettingsForm = this.createGenerationSettingsForm();
    }

    ngOnInit(): void {
        this.setupApiTypeListener();
        this.setupActiveProviderListener();
        this.loadConfigAndPresets();
        this.localizationService.init();
    }

    private createMainForm(): UntypedFormGroup {
        return this.fb.group({
            apiType: ['Ollama'],
            activeProvider: ['ollama'],
            fallbackOrder: [''],
            visualModel: ['apple/FastVLM-1.5B'],
            visualModelOptions: [[]],
            tokenLimit: [2048],
            messagePairLimit: [4],
            streaming: [true],
            providers: this.fb.group({})
        });
    }

    private createGenerationSettingsForm(): UntypedFormGroup {
        return this.fb.group({
            name: [''],
            description: [''],
            temperature: [1.2],
            topP: [0.9],
            topK: [70],
            minP: [0.05],
            repeatPenalty: [1.2],
            numPredict: [2048],
            normalizeMessages: [false],
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
        ).pipe(takeUntil(this.destroy$)).subscribe(([config, presets, models]) => {
            // Load config
            if (config) {
                this.originalConfig = JSON.parse(JSON.stringify(config));

                this.initializeProviders(config.api?.providers || {});
                const normalizedActiveProvider = this.normalizeProviderKey(
                    config.api?.activeProvider || this.providerKeys[0] || 'ollama'
                );
                const tokenLimit = this.resolveInitialTokenLimit(config.api, normalizedActiveProvider);
                const messagePairLimit = this.normalizeNumberInRange(
                    config.api?.messagePairLimit,
                    4,
                    1,
                    50
                );
                const visualModel = String(config.api?.visualModel || '').trim();
                const visualModelOptions = this.mergeUniqueStrings([
                    ...this.normalizeStringList(config.api?.visualModelOptions),
                    visualModel,
                ]);
                if (this.originalConfig?.api) {
                    this.originalConfig.api.visualModelOptions = visualModelOptions;
                    this.originalConfig.api.tokenLimit = tokenLimit;
                }

                this.generationForm.patchValue({
                    apiType: this.capitalize(config.api.activeProvider || config.api.type || 'ollama'),
                    activeProvider: normalizedActiveProvider,
                    fallbackOrder: this.stringifyFallbackOrder(
                        config.api.fallbackOrder || []
                    ),
                    visualModel,
                    visualModelOptions,
                    tokenLimit,
                    messagePairLimit,
                    streaming: config.api?.streaming !== false,
                }, { emitEvent: false });
                this.visualModelManualOptions = visualModelOptions;

                this.apiTypeOptions = Array.from(
                    new Set([
                        ...(this.apiTypeOptions || []),
                        this.capitalize(config.api.activeProvider || config.api.type || 'ollama'),
                        ...this.providerKeys.map(key => this.capitalize(key)),
                    ].filter(Boolean))
                );

                const generateSettings = this.normalizeGenerationSettings(config.generateSettings);
                this.generationSettingsForm.patchValue(generateSettings, { emitEvent: false });

                const activeProvider = normalizedActiveProvider;
                this.selectedModel = this.getProviderModel(activeProvider);
                this.updateAvailableModels(activeProvider);
            }

            // Load presets
            this.presets = presets;
            const currentPresetName = this.generationSettingsForm.get('name')?.value;
            const activePreset = presets.find(p => p.name === currentPresetName) || presets[0];
            this.selectedPresetName = currentPresetName || activePreset?.name || this.selectedPresetName;

            // Load models
            this.ollamaModels = (models || []).filter(Boolean);
            const activeProvider = this.generationForm.get('activeProvider')?.value;
            this.updateAvailableModels(activeProvider);
        });
    }

    private initializeProviders(providers: Record<string, any>): void {
        const providersGroup = this.generationForm.get('providers') as UntypedFormGroup;
        if (!providersGroup) {
            return;
        }

        // Очистим предыдущие контролы
        Object.keys(providersGroup.controls).forEach(key => {
            providersGroup.removeControl(key);
        });

        const normalizedProviders = this.withBuiltInProviders(providers || {});
        this.providerKeys = Object.keys(normalizedProviders);
        this.apiTypeOptions = Array.from(
            new Set(
                [this.generationForm.get('apiType')?.value, ...this.providerKeys.map(key => this.capitalize(key))]
                    .filter(Boolean)
            )
        );

        this.providerKeys.forEach(key => {
            providersGroup.addControl(key, this.buildProviderGroup(normalizedProviders[key] || {}));
        });
    }

    private withBuiltInProviders(providers: Record<string, any>): Record<string, any> {
        const normalized = { ...(providers || {}) };
        Object.keys(this.builtInProviderDefaults).forEach((key) => {
            normalized[key] = {
                ...this.builtInProviderDefaults[key],
                ...(normalized[key] || {}),
            };
        });
        return normalized;
    }

    private buildProviderGroup(config: Record<string, any>): UntypedFormGroup {
        const controls: Record<string, any> = {};
        Object.keys(config || {}).forEach(field => {
            controls[field] = [config[field]];
        });
        return this.fb.group(controls);
    }

    private setupActiveProviderListener(): void {
        this.generationForm.get('activeProvider')?.valueChanges
            .pipe(takeUntil(this.destroy$), distinctUntilChanged())
            .subscribe(provider => {
                this.handleActiveProviderChange(provider);
            });
    }

    private setupApiTypeListener(): void {
        this.generationForm.get('apiType')?.valueChanges
            .pipe(takeUntil(this.destroy$), distinctUntilChanged())
            .subscribe(value => {
                const provider = this.providerKeyFromApiType(value);
                if (!provider) {
                    return;
                }
                this.generationForm.get('activeProvider')?.setValue(provider);
            });
    }

    private handleActiveProviderChange(provider: string): void {
        const normalized = this.normalizeProviderKey(provider);
        this.selectedModel = this.getProviderModel(normalized);
        this.generationForm.get('apiType')?.setValue(this.capitalize(normalized), { emitEvent: false });
        this.updateAvailableModels(normalized);
        this.dropdownOpen = false;
    }

    private updateAvailableModels(provider: string): void {
        const normalizedProvider = this.normalizeProviderKey(provider);
        if (normalizedProvider === 'ollama') {
            const currentModel = this.getProviderModel(normalizedProvider);
            this.availableModels = Array.from(
                new Set([
                    ...(currentModel ? [currentModel] : []),
                    ...(this.ollamaModels || []),
                ])
            );
        } else {
            this.availableModels = [];
        }
    }

    private getProviderModel(provider: string): string {
        const providerGroup = this.getProviderForm(provider);
        return (providerGroup?.get('model')?.value as string) || '';
    }

    private getProviderForm(provider: string): UntypedFormGroup | null {
        const providersGroup = this.generationForm.get('providers') as UntypedFormGroup;
        if (!providersGroup || !provider) {
            return null;
        }
        const normalizedProvider = this.normalizeProviderKey(provider);
        const direct = providersGroup.get(normalizedProvider) as UntypedFormGroup;
        if (direct) {
            return direct;
        }
        const matchedKey = Object.keys(providersGroup.controls).find(
            key => this.normalizeProviderKey(key) === normalizedProvider
        );
        return matchedKey ? (providersGroup.get(matchedKey) as UntypedFormGroup) : null;
    }

    onTokenLimitRangeChange(value: number): void {
        this.generationForm.get('tokenLimit')?.setValue(
            this.normalizeNumberInRange(value, 2048, this.tokenLimitMin, this.tokenLimitMax)
        );
    }

    onTokenLimitInputCommit(): void {
        const control = this.generationForm.get('tokenLimit');
        control?.setValue(this.tokenLimitValue);
    }

    openVisualModelDropdown(): void {
        this.visualModelDropdownOpen = true;
    }

    closeVisualModelDropdown(): void {
        window.setTimeout(() => {
            this.visualModelDropdownOpen = false;
        }, 120);
    }

    selectVisualModel(model: string): void {
        const value = String(model || '').trim();
        if (!value) {
            return;
        }
        this.generationForm.get('visualModel')?.setValue(value);
        this.visualModelDropdownOpen = false;
    }

    addCurrentVisualModelOption(): void {
        const value = String(this.generationForm.get('visualModel')?.value || '').trim();
        if (!value) {
            return;
        }
        const next = this.mergeUniqueStrings([...this.visualModelManualOptions, value]);
        this.visualModelManualOptions = next;
        this.generationForm.get('visualModelOptions')?.setValue(next);
        this.generationForm.get('visualModelOptions')?.markAsDirty();
    }

    removeVisualModelOption(model: string, event?: MouseEvent): void {
        event?.preventDefault();
        event?.stopPropagation();
        const value = String(model || '').trim();
        const next = this.visualModelManualOptions.filter((item) => item !== value);
        this.visualModelManualOptions = next;
        this.generationForm.get('visualModelOptions')?.setValue(next);
        this.generationForm.get('visualModelOptions')?.markAsDirty();
    }

    toggleDropdown() {
        if (!this.isOllamaActiveProvider) {
            return;
        }
        if (!this.availableModels || this.availableModels.length === 0) {
            return;
        }
        this.dropdownOpen = !this.dropdownOpen;
    }

    selectModel(model: string) {
        this.selectedModel = model;
        this.dropdownOpen = false;
        const activeProvider = this.normalizeProviderKey(this.generationForm.get('activeProvider')?.value);
        const providerForm = this.getProviderForm(activeProvider);
        providerForm?.get('model')?.setValue(model);
    }

    applyPreset(presetName: string) {
        const preset = this.presets.find(p => p.name === presetName);
        if (preset) {
            this.generationSettingsForm.patchValue(this.normalizeGenerationSettings(preset));
            this.selectedPresetName = presetName;
        }
    }

    saveOrUpdatePreset() {
        const current = this.generationSettingsForm.value;
        this.configService.saveGenerationPreset$(current).subscribe({
            next: () => {
                this.configService.getGenerationPresets$().pipe(takeUntil(this.destroy$)).subscribe((presets) => {
                    this.presets = presets || [];
                    this.selectedPresetName = current.name || this.selectedPresetName;
                });
                this.notificationService.open({
                    title: 'Generation preset saved',
                    type: 'success',
                    autoClose: true,
                });
            },
            error: (error) => {
                this.notificationService.open({
                    title: 'Error saving generation preset',
                    type: 'error',
                    autoClose: true,
                });
                console.error('Error saving generation preset:', error);
            },
        });
    }

    saveChanges(): void {
        if (!this.originalConfig) {
            return;
        }
        const updateData: any = {};
        const currentApi = this.buildCurrentApiConfig();
        const currentGenerateSettings = this.generationSettingsForm.value;

        if (!this.deepEqual(currentApi, this.originalConfig?.api)) {
            updateData.api = currentApi;
        }

        if (!this.deepEqual(currentGenerateSettings, this.originalConfig?.generateSettings)) {
            updateData.generateSettings = currentGenerateSettings;
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
                    this.originalConfig = JSON.parse(JSON.stringify({
                        api: currentApi,
                        generateSettings: currentGenerateSettings,
                    }));
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

    onPresetChange(event: any): void {
        const value = event?.target?.value;
        if (typeof value === 'string') {
            this.applyPreset(value);
        }
    }
    hasChanges(): boolean {
        if (!this.originalConfig) {
            return false;
        }
        const currentApi = this.buildCurrentApiConfig();
        const currentGenerateSettings = this.generationSettingsForm.value;
        return (
            !this.deepEqual(currentApi, this.originalConfig?.api) ||
            !this.deepEqual(currentGenerateSettings, this.originalConfig?.generateSettings)
        );
    }

    private buildCurrentApiConfig(): any {
        const values = this.generationForm.value;
        const providersGroup = this.generationForm.get('providers') as UntypedFormGroup;
        const providerValues: Record<string, any> = {};

        Object.keys(providersGroup?.controls || {}).forEach(key => {
            providerValues[key] = providersGroup.get(key)?.value;
        });

        const activeProvider = this.normalizeProviderKey(values.activeProvider);
        const fallbackOrder = this.parseFallbackOrder(values.fallbackOrder);
        const activeModel = this.getProviderForm(activeProvider)?.get('model')?.value || '';

        return {
            type: values.apiType,
            streaming: values.streaming,
            visualModel: values.visualModel,
            visualModelOptions: this.normalizeStringList(values.visualModelOptions),
            tokenLimit: this.normalizeNumberInRange(values.tokenLimit, 2048, this.tokenLimitMin, this.tokenLimitMax),
            messagePairLimit: values.messagePairLimit,
            activeProvider,
            fallbackOrder,
            providers: providerValues,
            model: activeModel,
        };
    }

    private parseFallbackOrder(value: string): string[] {
        if (!value) {
            return [];
        }
        return value
            .split(',')
            .map(item => item.trim())
            .filter(Boolean);
    }

    private stringifyFallbackOrder(order: string[]): string {
        return (order || []).join(', ');
    }

    private deepEqual(a: any, b: any): boolean {
        return JSON.stringify(a) === JSON.stringify(b);
    }

    get currentProviderForm(): UntypedFormGroup | null {
        const activeProvider = this.normalizeProviderKey(this.generationForm.get('activeProvider')?.value);
        return this.getProviderForm(activeProvider);
    }

    get currentProviderFields(): Array<{ key: string; type: 'text' | 'number' | 'checkbox' }> {
        const group = this.currentProviderForm;
        if (!group) {
            return [];
        }
        return Object.keys(group.controls).map(field => {
            const value = group.get(field)?.value;
            let type: 'text' | 'number' | 'checkbox' = 'text';
            if (typeof value === 'number') {
                type = 'number';
            } else if (typeof value === 'boolean') {
                type = 'checkbox';
            }
            return { key: field, type };
        });
    }

    formatFieldLabel(field: string): string {
        return field
            .replace(/_/g, ' ')
            .replace(/\b\w/g, letter => letter.toUpperCase());
    }

    private capitalize(value: string): string {
        if (!value) {
            return value;
        }
        return value.charAt(0).toUpperCase() + value.slice(1);
    }

    private normalizeProviderKey(value: any): string {
        return String(value || '')
            .trim()
            .toLowerCase();
    }

    private providerKeyFromApiType(value: any): string {
        const normalized = this.normalizeProviderKey(value);
        if (!normalized) {
            return '';
        }
        return (this.providerKeys || []).find(key => this.normalizeProviderKey(key) === normalized)
            || normalized;
    }

    private normalizeNumberInRange(value: any, fallback: number, min: number, max: number): number {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return fallback;
        }
        const rounded = Math.round(parsed);
        return Math.max(min, Math.min(max, rounded));
    }

    private normalizeFloatInRange(value: any, fallback: number, min: number, max: number): number {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return fallback;
        }
        return Math.max(min, Math.min(max, parsed));
    }

    private normalizeGenerationSettings(value: any): any {
        const source = value || {};
        const normalized = {
            ...this.generationDefaults,
            ...source,
            temperature: this.normalizeFloatInRange(source.temperature, this.generationDefaults.temperature, 0.1, 2.0),
            topP: this.normalizeFloatInRange(source.topP ?? source.top_p, this.generationDefaults.topP, 0.1, 1.0),
            topK: this.normalizeNumberInRange(source.topK ?? source.top_k, this.generationDefaults.topK, 1, 100),
            minP: this.normalizeFloatInRange(source.minP ?? source.min_p, this.generationDefaults.minP, 0, 1.0),
            repeatPenalty: this.normalizeFloatInRange(source.repeatPenalty ?? source.repeat_penalty, this.generationDefaults.repeatPenalty, 0.5, 2.0),
            numPredict: this.normalizeNumberInRange(source.numPredict ?? source.num_predict, this.generationDefaults.numPredict, 64, 4096),
            normalizeMessages: (source.normalizeMessages ?? source.normalize_messages) === true,
            stop: Array.isArray(source.stop) ? source.stop : this.generationDefaults.stop,
        };
        return normalized;
    }

    private resolveInitialTokenLimit(api: any, activeProvider: string): number {
        const primary = Number(api?.tokenLimit);
        if (Number.isFinite(primary) && primary >= this.tokenLimitMin) {
            return this.normalizeNumberInRange(primary, 2048, this.tokenLimitMin, this.tokenLimitMax);
        }

        const providerKey = this.normalizeProviderKey(activeProvider);
        const providerLimit = Number(api?.providers?.[providerKey]?.maxTokens);
        if (Number.isFinite(providerLimit) && providerLimit >= this.tokenLimitMin) {
            return this.normalizeNumberInRange(providerLimit, 2048, this.tokenLimitMin, this.tokenLimitMax);
        }

        return 2048;
    }

    private normalizeStringList(value: any): string[] {
        if (!Array.isArray(value)) {
            return [];
        }
        return this.mergeUniqueStrings(value);
    }

    private mergeUniqueStrings(values: any[]): string[] {
        return Array.from(new Set(
            (values || [])
                .map((item) => String(item || '').trim())
                .filter(Boolean)
        ));
    }

    get apiTypeSelectOptions(): UiSelectOption[] {
        return (this.apiTypeOptions || []).map(option => ({
            value: option,
            label: option,
        }));
    }

    get activeProviderOptions(): UiSelectOption[] {
        return (this.providerKeys || []).map(provider => ({
            value: provider,
            label: this.capitalize(provider),
        }));
    }

    get presetOptions(): UiSelectOption[] {
        return (this.presets || []).map((preset) => ({
            value: preset.name,
            label: preset.name,
        }));
    }

    get visualModelOptions(): UiSelectOption[] {
        return (this.ollamaModels || []).map((model) => ({
            value: model,
            label: model,
        }));
    }

    get isOllamaActiveProvider(): boolean {
        return this.normalizeProviderKey(this.generationForm.get('activeProvider')?.value) === 'ollama';
    }

    get tokenLimitValue(): number {
        return this.normalizeNumberInRange(
            this.generationForm.get('tokenLimit')?.value,
            2048,
            this.tokenLimitMin,
            this.tokenLimitMax
        );
    }

    get visualModelOllamaOptions(): string[] {
        return this.mergeUniqueStrings(this.ollamaModels);
    }

    get hasVisualModelDropdownItems(): boolean {
        return this.visualModelManualOptions.length > 0 || this.isOllamaActiveProvider;
    }

    trackByProviderField(_index: number, field: { key: string }): string {
        return field.key;
    }

    ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }
}
