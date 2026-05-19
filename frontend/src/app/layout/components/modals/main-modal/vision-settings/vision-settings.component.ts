import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormControl, UntypedFormGroup } from '@angular/forms';
import { BehaviorSubject, Subject } from 'rxjs';
import { finalize, take, takeUntil } from 'rxjs/operators';
import { ConfigService } from '../../../../../core/services/config.service';
import { ResourcesService } from '../../../../../core/services/resources.service';
import { ApiService } from '../../../../../core/services/api.service';
import { ModalService } from '../../../../../shared/components/modal/modal.service';
import { MonitorSelectionModalComponent } from '../../monitor-selection-modal/monitor-selection-modal.component';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';

type ProviderFieldType = 'text' | 'number' | 'boolean';

interface ProviderFieldMeta {
    key: string;
    label: string;
    type: ProviderFieldType;
}

interface VisionProviderStatusView {
    provider: string;
    model: string;
    ready: boolean | null;
    message: string;
    probe: boolean;
}

const VISION_PROVIDER_DEFAULTS: Record<string, Record<string, any>> = {
    apple_vision: { model_id: 'apple/FastVLM-1.5B', max_tokens: 128 },
    llava: { model_id: 'llava-hf/llava-1.5-7b-hf', max_tokens: 128 },
    ollama_vision: { model: 'llava:latest', max_tokens: 512, probe_enabled: true, probe_cache_seconds: 300, image_format: 'PNG', keep_alive: '5m', use_main_model_context: false },
};

@Component({
    selector: 'app-vision-settings',
    templateUrl: './vision-settings.component.html',
    styleUrls: ['./vision-settings.component.less']
})
export class VisionSettingsComponent implements OnInit, OnDestroy {
    visionForm: UntypedFormGroup;
    originalConfig: any = {};
    originalModules: any = {};

    visionProviders: { value: string; label: string }[] = [];
    isLoading$ = new BehaviorSubject<boolean>(true);
    isCheckingProvider = false;
    providerStatus: VisionProviderStatusView | null = null;
    ollamaModels: string[] = [];
    isLoadingOllamaModels = false;

    private providerFieldMeta: Record<string, ProviderFieldMeta[]> = {};
    private providerFieldTypes: Record<string, Record<string, ProviderFieldType>> = {};
    private pendingChanges: any = {};
    private destroy$ = new Subject<void>();
    private isInitializing = true;

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private resourcesService: ResourcesService,
        private apiService: ApiService,
        private modalService: ModalService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.visionForm = this.createForm();
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.setupListeners();
        this.loadConfig();
    }

    ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            enabled: [false],
            activeProvider: [''],
            monitorIndex: [0],
            fps: [5],
            bufferSec: [4],
            downscaleWidth: [1280],
            yoloEnabled: [false],
            ocrLang: ['rus+eng'],
            ocrMinConf: [70],
            ocrMaxLines: [5],
            region: [null],
            captureMode: ['monitor'],
            windowTitle: [''],
            windowProcess: [''],
            debugSave: [true],
            debugPath: ['./temp/vision'],
            visionModules: this.fb.group({})
        });
    }

    private setupListeners(): void {
        this.visionForm.valueChanges
            .pipe(takeUntil(this.destroy$))
            .subscribe(() => {
                if (this.isInitializing) {
                    return;
                }
                this.pendingChanges = this.calculateChanges();
            });

        this.visionForm.get('activeProvider')?.valueChanges
            .pipe(takeUntil(this.destroy$))
            .subscribe((providerName: string) => {
                if (!providerName) {
                    return;
                }
                this.ensureProviderGroup(providerName);
                if (providerName === 'ollama_vision') {
                    this.loadOllamaModels();
                }
                this.refreshProviderStatus(false);
            });
    }

    private loadConfig(): void {
        this.isLoading$.next(true);
        this.configService.getConfig$()
            .pipe(
                take(1),
                takeUntil(this.destroy$),
                finalize(() => this.isLoading$.next(false))
            )
            .subscribe({
                next: (config) => {
                    const vision = config?.vision;
                    this.originalModules = this.normalizeModulesPayload(config?.modules);
                    this.isInitializing = true;
                    this.resetProviderControls();

                    if (vision) {
                        this.populateProviders(vision.visionModules || {});

                        const activeProvider = vision.activeProvider || this.visionProviders[0]?.value || '';

                        this.visionForm.patchValue({
                            enabled: vision.enabled ?? false,
                            activeProvider,
                            monitorIndex: vision.monitorIndex ?? 0,
                            fps: vision.fps ?? 5,
                            bufferSec: vision.bufferSec ?? 4,
                            downscaleWidth: vision.downscaleWidth ?? 1280,
                            yoloEnabled: vision.yoloEnabled ?? false,
                            ocrLang: vision.ocrLang ?? 'eng',
                            ocrMinConf: vision.ocrMinConf ?? 70,
                            ocrMaxLines: vision.ocrMaxLines ?? 5,
                            region: vision.region ?? null,
                            captureMode: vision.captureMode ?? 'monitor',
                            windowTitle: vision.windowTitle ?? '',
                            windowProcess: vision.windowProcess ?? '',
                            debugSave: vision.debugSave ?? true,
                            debugPath: vision.debugPath ?? './temp/vision',
                        }, { emitEvent: false });

                        this.ensureProviderGroup(activeProvider);
                        if (activeProvider === 'ollama_vision') {
                            this.loadOllamaModels();
                        }
                    } else {
                        this.populateProviders({});
                    }

                    this.originalConfig = this.buildVisionConfigFromForm();
                    this.pendingChanges = {};
                    this.visionForm.markAsPristine();
                    this.isInitializing = false;
                    this.refreshProviderStatus(false);
                    this.cdr.markForCheck();
                },
                error: (error) => {
                    console.error('Failed to load vision config', error);
                    this.notificationService.open({
                        title: 'Error',
                        type: 'error',
                        message: 'Failed to load vision configuration',
                        autoClose: true,
                    });
                    this.isInitializing = false;
                    this.cdr.markForCheck();
                }
            });
    }

    openMonitorSelection(): void {
        this.resourcesService.getMonitorScreens$()
            .pipe(take(1), takeUntil(this.destroy$))
            .subscribe(response => {
            if (response && response.monitors) {
                const modalRef = this.modalService.open(MonitorSelectionModalComponent, {
                    title: 'Select Monitor',
                    appearance: 'default',
                    data: {
                        monitors: response.monitors,
                        selectedMonitor: this.visionForm.get('monitorIndex')?.value,
                        onSelect: (result: any) => {
                            if (result && result.selectedMonitor !== undefined) {
                                const value = Number(result.selectedMonitor);
                                if (!Number.isNaN(value)) {
                                    this.visionForm.get('monitorIndex')?.setValue(value);
                                }
                            }
                        }
                    }
                });

                modalRef.afterClosed$.pipe(take(1)).subscribe((response) => {
                    const selectedMonitor = response?.selectedMonitor;
                    if (selectedMonitor !== undefined) {
                        const value = Number(selectedMonitor);
                        if (!Number.isNaN(value)) {
                            this.visionForm.get('monitorIndex')?.setValue(value);
                        }
                    }
                });
            }
        });
    }

    saveChanges(): void {
        const changes = this.pendingChanges;
        const modules = this.buildModulesPayload();
        const updateData: any = {};
        if (changes && Object.keys(changes).length > 0) {
            updateData.vision = JSON.parse(JSON.stringify(changes));
        }
        if (JSON.stringify(modules) !== JSON.stringify(this.originalModules)) {
            updateData.modules = modules;
        }
        if (Object.keys(updateData).length === 0) {
            return;
        }

        this.configService.updateConfig$(updateData)
            .pipe(take(1), takeUntil(this.destroy$))
            .subscribe({
                next: () => {
                    this.notificationService.open({
                        message: 'Vision settings updated',
                        title: 'Success',
                        type: 'success',
                        autoClose: true
                    });
                    this.isInitializing = true;
                    this.originalConfig = this.buildVisionConfigFromForm();
                    this.originalModules = modules;
                    this.pendingChanges = {};
                    this.visionForm.markAsPristine();
                    this.isInitializing = false;
                    this.cdr.markForCheck();
                },
                error: (error) => {
                    console.error('Error updating vision settings:', error);
                    this.notificationService.open({
                        message: 'Failed to update vision settings',
                        title: 'Error',
                        type: 'error',
                        autoClose: false
                    });
                    this.cdr.markForCheck();
                }
            });
    }

    hasChanges(): boolean {
        const modules = this.buildModulesPayload();
        return (
            (!!this.pendingChanges && Object.keys(this.pendingChanges).length > 0) ||
            JSON.stringify(modules) !== JSON.stringify(this.originalModules)
        );
    }

    private normalizeModulesPayload(modules: any): any {
        const source = modules || {};
        return {
            vtubeStudio: !!(source.vtubeStudio ?? source.vtube_studio),
            whisper: !!source.whisper,
            minecraft: !!source.minecraft,
            gaming: !!source.gaming,
            alarm: !!source.alarm,
            discord: !!source.discord,
            telegram: !!source.telegram,
            rag: !!source.rag,
            visual: !!source.visual,
        };
    }

    private buildModulesPayload(): any {
        return {
            ...this.originalModules,
            visual: !!this.visionForm.get('enabled')?.value,
        };
    }

    get visionProviderOptions(): UiSelectOption<string>[] {
        return this.visionProviders.map((provider) => ({
            value: provider.value,
            label: provider.label,
        }));
    }

    get captureModeOptions(): UiSelectOption<string>[] {
        return [
            {
                value: 'monitor',
                label: this.localizationService.t('settings.monitor'),
            },
            {
                value: 'window',
                label: this.localizationService.t('settings.window'),
            },
            {
                value: 'region',
                label: this.localizationService.t('settings.region'),
            },
        ];
    }

    get ollamaModelOptions(): UiSelectOption<string>[] {
        return this.ollamaModels.map((item) => ({
            value: item,
            label: item,
        }));
    }

    get activeProvider(): string {
        return this.visionForm.get('activeProvider')?.value;
    }

    get currentProviderGroup(): UntypedFormGroup | null {
        const provider = this.activeProvider;
        if (!provider) {
            return null;
        }
        return (this.visionForm.get('visionModules') as UntypedFormGroup)?.get(provider) as UntypedFormGroup;
    }

    checkProviderCapability(): void {
        this.refreshProviderStatus(true);
    }

    refreshOllamaModels(): void {
        this.loadOllamaModels(true);
    }

    getProviderFields(providerName: string): ProviderFieldMeta[] {
        return this.providerFieldMeta[providerName] ?? [];
    }

    getProviderLabel(providerName: string): string {
        return this.visionProviders.find(provider => provider.value === providerName)?.label || this.formatLabel(providerName);
    }

    private resetProviderControls(): void {
        this.providerFieldMeta = {};
        this.providerFieldTypes = {};
        this.visionProviders = [];
        this.visionForm.setControl('visionModules', this.fb.group({}));
    }

    private populateProviders(modules: Record<string, any>): void {
        const mergedModules: Record<string, any> = { ...(modules || {}) };
        Object.keys(VISION_PROVIDER_DEFAULTS).forEach((providerName) => {
            if (!mergedModules[providerName]) {
                mergedModules[providerName] = { ...VISION_PROVIDER_DEFAULTS[providerName] };
            }
        });
        const providers = Object.keys(mergedModules);
        const modulesGroup = this.fb.group({});

        providers.forEach((providerName) => {
            const providerConfig = mergedModules[providerName] || {};
            modulesGroup.addControl(providerName, this.createProviderGroup(providerName, providerConfig));
        });

        this.visionForm.setControl('visionModules', modulesGroup);
        this.visionProviders = providers.map(providerName => ({
            value: providerName,
            label: this.formatLabel(providerName)
        }));
    }

    private ensureProviderGroup(providerName: string): void {
        const modulesGroup = this.visionForm.get('visionModules') as UntypedFormGroup;
        if (!modulesGroup) {
            return;
        }

        if (!modulesGroup.get(providerName)) {
            modulesGroup.addControl(
                providerName,
                this.createProviderGroup(providerName, VISION_PROVIDER_DEFAULTS[providerName] || {}),
            );
        }
    }

    private loadOllamaModels(forceReload = false): void {
        if (this.isLoadingOllamaModels) {
            return;
        }
        if (!forceReload && this.ollamaModels.length > 0) {
            return;
        }
        this.isLoadingOllamaModels = true;
        this.apiService.getOllamaModels$()
            .pipe(take(1), takeUntil(this.destroy$))
            .subscribe({
                next: (models) => {
                    this.ollamaModels = Array.isArray(models) ? models : [];
                    if (this.activeProvider === 'ollama_vision' && this.ollamaModels.length > 0) {
                        const group = this.currentProviderGroup;
                        const control = group?.get('model');
                        const current = String(control?.value || '').trim();
                        if (control && !current) {
                            control.setValue(this.ollamaModels[0], { emitEvent: true });
                        }
                    }
                    this.isLoadingOllamaModels = false;
                    this.cdr.markForCheck();
                },
                error: () => {
                    this.ollamaModels = [];
                    this.isLoadingOllamaModels = false;
                    this.cdr.markForCheck();
                },
            });
    }

    private refreshProviderStatus(probe: boolean): void {
        const provider = String(this.activeProvider || '').trim();
        if (!provider) {
            this.providerStatus = null;
            return;
        }
        const group = this.currentProviderGroup;
        const model = String(
            group?.get('model')?.value
            ?? group?.get('model_id')?.value
            ?? ''
        ).trim();
        this.providerStatus = {
            provider,
            model,
            ready: this.providerStatus?.ready ?? null,
            message: probe ? 'checking...' : (this.providerStatus?.message || 'not checked'),
            probe,
        };
        this.isCheckingProvider = true;
        this.resourcesService.getVisionProviderStatus$(provider, model || null, probe)
            .pipe(take(1), takeUntil(this.destroy$))
            .subscribe({
                next: (response) => {
                    const payload = response?.provider || {};
                    this.providerStatus = {
                        provider: String(payload.name || provider),
                        model: String(payload.model || model || ''),
                        ready: typeof payload.ready === 'boolean' ? payload.ready : null,
                        message: String(payload.message || 'unknown'),
                        probe: !!payload.probe,
                    };
                    this.isCheckingProvider = false;
                    this.cdr.markForCheck();
                },
                error: () => {
                    this.providerStatus = {
                        provider,
                        model: model || '',
                        ready: false,
                        message: 'status request failed',
                        probe,
                    };
                    this.isCheckingProvider = false;
                    this.cdr.markForCheck();
                }
            });
    }

    private createProviderGroup(providerName: string, providerConfig: Record<string, any>): UntypedFormGroup {
        const group = this.fb.group({});
        Object.keys(providerConfig || {}).forEach((fieldName) => {
            group.addControl(fieldName, new UntypedFormControl(providerConfig[fieldName]));
        });

        group.valueChanges
            .pipe(takeUntil(this.destroy$))
            .subscribe((value) => {
                if (this.isInitializing || providerName !== this.activeProvider) {
                    return;
                }
                const model = String(value?.model ?? value?.model_id ?? '').trim();
                this.providerStatus = {
                    provider: providerName,
                    model,
                    ready: null,
                    message: 'not checked',
                    probe: false,
                };
                this.cdr.markForCheck();
            });

        this.setProviderMetadata(providerName, providerConfig || {});

        return group;
    }

    private setProviderMetadata(providerName: string, providerConfig: Record<string, any>): void {
        const meta: ProviderFieldMeta[] = [];
        const typeMap: Record<string, ProviderFieldType> = {};

        Object.keys(providerConfig || {}).forEach((fieldName) => {
            const value = providerConfig[fieldName];
            const type = this.detectFieldType(value);
            const fieldMeta: ProviderFieldMeta = {
                key: fieldName,
                label: this.formatLabel(fieldName),
                type
            };

            meta.push(fieldMeta);
            typeMap[fieldName] = type;
        });

        this.providerFieldMeta[providerName] = meta;
        this.providerFieldTypes[providerName] = typeMap;
    }

    private detectFieldType(value: any): ProviderFieldType {
        if (typeof value === 'boolean') {
            return 'boolean';
        }
        if (typeof value === 'number') {
            return 'number';
        }
        return 'text';
    }

    private formatLabel(fieldName: string): string {
        return fieldName
            .replace(/_/g, ' ')
            .replace(/([A-Z])/g, ' $1')
            .replace(/\s+/g, ' ')
            .trim()
            .replace(/\b\w/g, (char) => char.toUpperCase());
    }

    private buildVisionConfigFromForm(): any {
        const raw = this.visionForm.getRawValue();
        const modulesGroup = raw.visionModules || {};
        const modules: Record<string, any> = {};

        Object.keys(modulesGroup).forEach((providerName) => {
            const providerValues = modulesGroup[providerName] || {};
            modules[providerName] = Object.keys(providerValues).reduce((acc: Record<string, any>, fieldName: string) => {
                let value = providerValues[fieldName];

                const fieldType = this.providerFieldTypes[providerName]?.[fieldName];
                if (fieldType === 'number' && value !== null && value !== '') {
                    value = Number(value);
                }

                acc[fieldName] = value;
                return acc;
            }, {});
        });

        return {
            enabled: raw.enabled,
            activeProvider: raw.activeProvider,
            monitorIndex: raw.monitorIndex,
            fps: raw.fps,
            bufferSec: raw.bufferSec,
            downscaleWidth: raw.downscaleWidth,
            yoloEnabled: raw.yoloEnabled,
            ocrLang: raw.ocrLang,
            ocrMinConf: raw.ocrMinConf,
            ocrMaxLines: raw.ocrMaxLines,
            region: raw.region,
            captureMode: raw.captureMode,
            windowTitle: raw.windowTitle,
            windowProcess: raw.windowProcess,
            debugSave: raw.debugSave,
            debugPath: raw.debugPath,
            visionModules: modules,
        };
    }

    private calculateChanges(): any {
        const current = this.buildVisionConfigFromForm();
        const diff = this.deepDiff(this.originalConfig || {}, current);
        return diff && typeof diff === 'object' ? diff : {};
    }

    private deepDiff(original: any, current: any): any {
        if (Array.isArray(current)) {
            if (!Array.isArray(original) || JSON.stringify(current) !== JSON.stringify(original)) {
                return current;
            }
            return undefined;
        }

        if (this.isPlainObject(current)) {
            const diff: Record<string, any> = {};

            Object.keys(current).forEach((key) => {
                const result = this.deepDiff(original ? original[key] : undefined, current[key]);
                if (this.hasValue(result)) {
                    diff[key] = result;
                }
            });

            return Object.keys(diff).length > 0 ? diff : undefined;
        }

        if (!this.isEqual(current, original)) {
            return current;
        }

        return undefined;
    }

    private hasValue(value: any): boolean {
        if (value === undefined) {
            return false;
        }

        if (Array.isArray(value)) {
            return value.length > 0;
        }

        if (this.isPlainObject(value)) {
            return Object.keys(value).length > 0;
        }

        return true;
    }

    private isPlainObject(value: any): value is Record<string, any> {
        return value !== null && typeof value === 'object' && !Array.isArray(value);
    }

    private isEqual(a: any, b: any): boolean {
        if (a === b) {
            return true;
        }
        return typeof a === 'number' && typeof b === 'number' && Number.isNaN(a) && Number.isNaN(b);
    }
}
