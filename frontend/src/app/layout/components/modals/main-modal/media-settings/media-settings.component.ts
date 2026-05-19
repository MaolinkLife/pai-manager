import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormArray, UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { SynthesisService } from '../../../../../core/services/synthesis.service';
import { UiNotificationService } from '../../../../../shared/ui/services/ui-notification.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { Subject } from 'rxjs';
import { takeUntil } from 'rxjs/operators';

@Component({
    selector: 'app-media-settings',
    templateUrl: './media-settings.component.html',
    styleUrls: ['./media-settings.component.less']
})
export class MediaSettingsComponent implements OnInit, OnDestroy {
    mediaForm: UntypedFormGroup;
    originalSynthesis: any = {};
    readonly imageProviderOptions: UiSelectOption[] = [
        { value: 'core', label: 'pai-image-gen' },
        { value: 'comfyui', label: 'ComfyUI' },
        { value: 'stable_diffusion_webui', label: 'Stable Diffusion WebUI' },
    ];
    readonly scenarioProviderOptions: UiSelectOption[] = [
        { value: '', label: 'Default provider' },
        { value: 'auto', label: 'Auto' },
        { value: 'core', label: 'pai-image-gen' },
        { value: 'comfyui', label: 'ComfyUI' },
        { value: 'stable_diffusion_webui', label: 'Stable Diffusion WebUI' },
    ];
    readonly comfyuiAspectRatioOptions: UiSelectOption[] = [
        { value: '1:1', label: '1:1 Square' },
        { value: '9:16', label: '9:16 Portrait' },
        { value: '16:9', label: '16:9 Landscape' },
        { value: '2:3', label: '2:3 Portrait' },
        { value: '3:2', label: '3:2 Landscape' },
        { value: '3:4', label: '3:4 Portrait' },
        { value: '4:3', label: '4:3 Landscape' },
        { value: '21:9', label: '21:9 Ultrawide' },
    ];
    readonly comfyuiSchedulerOptions: UiSelectOption[] = [
        { value: 'normal', label: 'normal' },
        { value: 'karras', label: 'karras' },
        { value: 'exponential', label: 'exponential' },
        { value: 'sgm_uniform', label: 'sgm_uniform' },
        { value: 'simple', label: 'simple' },
        { value: 'ddim_uniform', label: 'ddim_uniform' },
    ];
    readonly comfyuiSamplerOptions: UiSelectOption[] = [
        { value: 'euler', label: 'euler' },
        { value: 'euler_ancestral', label: 'euler_ancestral' },
        { value: 'dpmpp_2m', label: 'dpmpp_2m' },
        { value: 'dpmpp_2m_sde', label: 'dpmpp_2m_sde' },
        { value: 'dpmpp_sde', label: 'dpmpp_sde' },
        { value: 'ddim', label: 'ddim' },
    ];
    diffusersModelOptions: UiSelectOption[] = [
        { value: 'z_image_turbo', label: 'z_image_turbo' },
    ];
    comfyuiModelOptions: UiSelectOption[] = [];
    isComfyuiModelsLoading = false;
    private synthesisBase: any = {};
    private readonly destroy$ = new Subject<void>();

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private synthesisService: SynthesisService,
        private uiNotificationService: UiNotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.mediaForm = this.createForm();
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.loadConfig();
        this.loadLocalModelCatalog();
    }

    ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            active_provider: ['core'],
            sd_webui: this.fb.group({
                enabled: [false],
                base_url: ['http://127.0.0.1:7860'],
                bearer_token: [''],
                timeout_sec: [180],
                checkpoint: [''],
                sampler_name: ['DPM++ 2M'],
                scheduler: ['Automatic'],
                cfg_scale_default: [2.0],
            }),
            comfyui: this.fb.group({
                enabled: [false],
                base_url: ['http://127.0.0.1:8188'],
                websocket_url: ['ws://127.0.0.1:8188/ws'],
                timeout_sec: [180],
                default_workflow: [''],
                default_model: [''],
                sampler: ['euler'],
                scheduler: ['normal'],
                steps: [30],
                cfg: [7.0],
                width: [1024],
                height: [1024],
                aspect_ratio: ['1:1'],
            }),
            diffusers: this.fb.group({
                enabled: [true],
                device: ['auto'],
                default_model: ['z_image_turbo'],
                local_models_path: ['storage/models/image-generation'],
                cache_dir: [''],
                torch_dtype: ['auto'],
                sampler: ['euler'],
                scheduler: ['normal'],
                steps: [30],
                cfg: [7.0],
                width: [1024],
                height: [1024],
                aspect_ratio: ['1:1'],
                allow_comfyui_fallback: [true],
            }),
            prompting: this.fb.group({
                enabled: [true],
                max_attempts: [3],
                assess_enabled: [true],
                retry_enabled: [true],
                quality_threshold: [0.72],
                default_negative_prompt: ['(text:2), (signature:2), raw photo'],
                scenarios: this.fb.array([]),
            }),
        });
    }

    get scenarioControls(): UntypedFormArray {
        return this.mediaForm.get('prompting.scenarios') as UntypedFormArray;
    }

    private defaultScenarioRows(): any[] {
        return [
            {
                key: 'sandbox',
                title: 'Sandbox',
                enabled: true,
                use_prompt_builder: true,
                review_generated_image: true,
                use_visual_intent: false,
            },
            {
                key: 'telegram_command',
                title: 'Telegram command',
                enabled: true,
                use_prompt_builder: true,
                review_generated_image: true,
                use_visual_intent: true,
            },
            {
                key: 'telegram_tool',
                title: 'Telegram tool',
                enabled: true,
                use_prompt_builder: true,
                review_generated_image: true,
                use_visual_intent: true,
            },
            {
                key: 'main_chat',
                title: 'Main chat',
                enabled: true,
                use_prompt_builder: false,
                review_generated_image: false,
                use_visual_intent: true,
            },
        ];
    }

    private createScenarioGroup(value: any = {}): UntypedFormGroup {
        return this.fb.group({
            key: [value.key || 'custom'],
            title: [value.title || value.key || 'Custom scenario'],
            enabled: [value.enabled !== false],
            image_provider: [value.image_provider || ''],
            image_model: [value.image_model || ''],
            width: [value.width ?? ''],
            height: [value.height ?? ''],
            steps: [value.steps ?? value.num_inference_steps ?? ''],
            cfg: [value.cfg ?? value.guidance_scale ?? ''],
            sampler: [value.sampler || ''],
            scheduler: [value.scheduler || ''],
            use_prompt_builder: [!!value.use_prompt_builder],
            review_generated_image: [!!value.review_generated_image],
            use_visual_intent: [!!value.use_visual_intent],
            prompt_policy: [value.prompt_policy || ''],
            style_prompt: [value.style_prompt || ''],
            negative_prompt: [value.negative_prompt || ''],
            system_prompt: [value.system_prompt || ''],
        });
    }

    private patchScenarioControls(scenarios: any): void {
        const rows = this.scenarioControls;
        while (rows.length) {
            rows.removeAt(0);
        }
        const configured = scenarios && typeof scenarios === 'object' ? scenarios : {};
        const defaults = this.defaultScenarioRows();
        const merged = defaults.map((item) => ({
            ...item,
            ...(configured[item.key] || {}),
            key: item.key,
        }));
        Object.keys(configured)
            .filter((key) => !defaults.some((item) => item.key === key))
            .forEach((key) => merged.push({ ...configured[key], key }));
        merged.forEach((item) => rows.push(this.createScenarioGroup(item)));
    }

    addScenario(): void {
        const key = `custom_${this.scenarioControls.length + 1}`;
        this.scenarioControls.push(this.createScenarioGroup({ key, title: 'Custom scenario' }));
    }

    removeScenario(index: number): void {
        this.scenarioControls.removeAt(index);
    }

    private loadConfig(): void {
        this.configService.getConfig$()
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (config: any) => {
                    const synthesis = config?.synthesis || {};
                    this.synthesisBase = synthesis;
                    const activeProvider = this.resolveActiveProvider(synthesis);
                    const prompting = synthesis.prompting || {};
                    const scenarios = prompting.scenarios || synthesis.prompting?.scenarios || {};
                    const { scenarios: _ignoredScenarios, ...promptingForPatch } = prompting;
                    this.mediaForm.patchValue({
                        active_provider: activeProvider,
                        sd_webui: synthesis.sd_webui || {},
                        comfyui: synthesis.comfyui || {},
                        diffusers: synthesis.diffusers || {},
                        prompting: promptingForPatch,
                    });
                    this.patchScenarioControls(scenarios);
                    this.originalSynthesis = this.buildSynthesisForSave();
                    this.ensureComfyuiCurrentModelOption();
                    if (activeProvider === 'comfyui') {
                        this.loadComfyuiModelCatalog();
                    }
                    this.cdr.markForCheck();
                },
                error: () => {
                    this.cdr.markForCheck();
                },
            });
    }

    private loadLocalModelCatalog(): void {
        this.synthesisService.getModels$(true)
            .pipe(takeUntil(this.destroy$))
            .subscribe((payload) => {
                const diffusers = (payload?.models || []).filter((item) => {
                    const provider = String(item.capabilities?.provider || item.provider || '').toLowerCase();
                    return provider === 'core' || provider === 'diffusers';
                });
                const fallback = this.mediaForm.get('diffusers.default_model')?.value || 'z_image_turbo';
                if (!diffusers.length) {
                    this.diffusersModelOptions = [{ value: fallback, label: String(fallback) }];
                    this.cdr.markForCheck();
                    return;
                }

                const mapped = diffusers.map((item) => ({
                    value: item.model_id,
                    label: item.label || item.model_id,
                }));
                const unique = Array.from(new Map(mapped.map((item) => [item.value, item])).values());
                const hasCurrent = unique.some((item) => item.value === fallback);
                if (!hasCurrent) {
                    unique.unshift({ value: fallback, label: String(fallback) });
                }
                this.diffusersModelOptions = unique;
                this.cdr.markForCheck();
            });
    }

    loadComfyuiModelCatalog(refresh = false): void {
        if (this.isComfyuiModelsLoading) {
            return;
        }
        this.isComfyuiModelsLoading = true;
        this.synthesisService.getComfyUIStatus$(refresh)
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (response) => {
                    const checkpoints = response?.comfyui?.resources?.checkpoints || [];
                    const mapped = checkpoints.map((checkpoint) => ({
                        value: checkpoint,
                        label: checkpoint,
                    }));
                    this.comfyuiModelOptions = Array.from(
                        new Map(mapped.map((item) => [item.value, item])).values()
                    );
                    this.mergeComfyuiRuntimeOptions(response?.comfyui?.resources || {});
                    this.ensureComfyuiCurrentModelOption();
                    this.isComfyuiModelsLoading = false;
                    this.cdr.markForCheck();
                },
                error: (error) => {
                    console.error('ComfyUI model catalog error:', error);
                    this.comfyuiModelOptions = [];
                    this.ensureComfyuiCurrentModelOption();
                    this.isComfyuiModelsLoading = false;
                    this.cdr.markForCheck();
                },
            });
    }

    onActiveProviderChange(provider: string): void {
        const normalized = this.normalizeProvider(provider);
        this.mediaForm.patchValue({ active_provider: normalized });
        if (normalized === 'comfyui') {
            this.mediaForm.get('comfyui.enabled')?.setValue(true);
            this.loadComfyuiModelCatalog();
        } else if (normalized === 'stable_diffusion_webui') {
            this.mediaForm.get('sd_webui.enabled')?.setValue(true);
        } else if (normalized === 'core') {
            this.mediaForm.get('diffusers.enabled')?.setValue(true);
        }
    }

    isProviderActive(provider: string): boolean {
        return this.normalizeProvider(this.mediaForm.get('active_provider')?.value) === this.normalizeProvider(provider);
    }

    private resolveActiveProvider(synthesis: any): string {
        const configured = this.normalizeProvider(synthesis?.active_provider);
        if (configured) {
            return configured;
        }
        if (synthesis?.comfyui?.enabled) {
            return 'comfyui';
        }
        if (synthesis?.sd_webui?.enabled) {
            return 'stable_diffusion_webui';
        }
        return 'core';
    }

    private normalizeProvider(provider: any): string {
        const value = String(provider || '').trim().toLowerCase();
        if (value === 'sd_webui') {
            return 'stable_diffusion_webui';
        }
        if (value === 'diffusers') {
            return 'core';
        }
        if (value === 'core' || value === 'comfyui' || value === 'stable_diffusion_webui') {
            return value;
        }
        return '';
    }

    onComfyuiAspectRatioChange(value: string): void {
        this.applyAspectRatio('comfyui', value);
    }

    onCoreAspectRatioChange(value: string): void {
        this.applyAspectRatio('diffusers', value);
    }

    private applyAspectRatio(groupName: 'comfyui' | 'diffusers', value: string): void {
        const sizes: Record<string, { width: number; height: number }> = {
            '1:1': { width: 1024, height: 1024 },
            '9:16': { width: 768, height: 1344 },
            '16:9': { width: 1344, height: 768 },
            '2:3': { width: 832, height: 1216 },
            '3:2': { width: 1216, height: 832 },
            '3:4': { width: 896, height: 1152 },
            '4:3': { width: 1152, height: 896 },
            '21:9': { width: 1536, height: 640 },
        };
        const size = sizes[value];
        if (!size) {
            return;
        }
        this.mediaForm.patchValue({
            [groupName]: {
                aspect_ratio: value,
                width: size.width,
                height: size.height,
            },
        });
    }

    private mergeComfyuiRuntimeOptions(resources: any): void {
        const samplers = Array.isArray(resources?.samplers) ? resources.samplers : [];
        if (samplers.length) {
            this.mergeSelectOptions(this.comfyuiSamplerOptions as UiSelectOption[], samplers);
        }
        const schedulers = Array.isArray(resources?.schedulers) ? resources.schedulers : [];
        if (schedulers.length) {
            this.mergeSelectOptions(this.comfyuiSchedulerOptions as UiSelectOption[], schedulers);
        }
    }

    private mergeSelectOptions(target: UiSelectOption[], values: string[]): void {
        const existing = new Set(target.map((item) => item.value));
        values.forEach((value) => {
            if (!existing.has(value)) {
                target.push({ value, label: value });
            }
        });
    }

    private ensureComfyuiCurrentModelOption(): void {
        const current = String(this.mediaForm.get('comfyui.default_model')?.value || '').trim();
        if (!current) {
            return;
        }
        if (!this.comfyuiModelOptions.some((item) => item.value === current)) {
            this.comfyuiModelOptions = [
                { value: current, label: current },
                ...this.comfyuiModelOptions,
            ];
        }
    }

    saveChanges(): void {
        const synthesis = this.buildSynthesisForSave();
        if (JSON.stringify(synthesis) === JSON.stringify(this.originalSynthesis)) {
            return;
        }
        this.configService.updateConfig$({ synthesis }).pipe(takeUntil(this.destroy$)).subscribe({
            next: () => {
                this.synthesisService.invalidateCache();
                this.synthesisBase = synthesis;
                this.originalSynthesis = synthesis;
                this.uiNotificationService.success(
                    this.localizationService.t('mediaSettings.savedMessage'),
                    this.localizationService.t('mediaSettings.title'),
                );
                this.cdr.markForCheck();
            },
            error: (error) => {
                console.error('Media settings update error:', error);
                this.uiNotificationService.error(
                    this.localizationService.t('mediaSettings.saveFailedMessage'),
                    this.localizationService.t('mediaSettings.title'),
                );
                this.cdr.markForCheck();
            }
        });
    }

    hasChanges(): boolean {
        return JSON.stringify(this.buildSynthesisForSave()) !== JSON.stringify(this.originalSynthesis);
    }

    private buildSynthesisForSave(): any {
        const synthesis = this.mediaForm.value;
        const prompting = synthesis.prompting || {};
        const scenarios = this.scenarioControls.controls.reduce((acc: Record<string, any>, control) => {
            const raw = control.value || {};
            const key = String(raw.key || '').trim();
            if (!key) {
                return acc;
            }
            const cleanNumber = (value: any): number | undefined => {
                if (value === null || value === undefined || value === '') {
                    return undefined;
                }
                const numeric = Number(value);
                return Number.isFinite(numeric) ? numeric : undefined;
            };
            acc[key] = {
                title: String(raw.title || key).trim(),
                enabled: raw.enabled !== false,
                image_provider: String(raw.image_provider || '').trim(),
                image_model: String(raw.image_model || '').trim(),
                width: cleanNumber(raw.width),
                height: cleanNumber(raw.height),
                steps: cleanNumber(raw.steps),
                cfg: cleanNumber(raw.cfg),
                sampler: String(raw.sampler || '').trim(),
                scheduler: String(raw.scheduler || '').trim(),
                use_prompt_builder: !!raw.use_prompt_builder,
                review_generated_image: !!raw.review_generated_image,
                use_visual_intent: !!raw.use_visual_intent,
                prompt_policy: String(raw.prompt_policy || '').trim(),
                style_prompt: String(raw.style_prompt || '').trim(),
                negative_prompt: String(raw.negative_prompt || '').trim(),
                system_prompt: String(raw.system_prompt || '').trim(),
            };
            Object.keys(acc[key]).forEach((field) => acc[key][field] === undefined && delete acc[key][field]);
            return acc;
        }, {});
        return {
            ...(this.synthesisBase || {}),
            ...synthesis,
            prompting: {
                ...(this.synthesisBase?.prompting || {}),
                ...prompting,
                scenarios,
            },
        };
    }
}
