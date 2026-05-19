import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { finalize, take } from 'rxjs/operators';
import { NotificationService } from '../../shared/components/notification/notification.service';
import { UiSelectOption } from '../../shared/ui/components/ui-select/ui-select.component';
import {
    ComfyUIStatusResponse,
    SynthesisModelInfo,
    SynthesisService,
} from '../../core/services/synthesis.service';

type SynthesisTab = 'image' | 'video' | 'audio';

@Component({
    selector: 'app-synthesis',
    templateUrl: './synthesis.component.html',
    styleUrls: ['./synthesis.component.less'],
})
export class SynthesisComponent implements OnInit {
    @ViewChild('checkpointInput') checkpointInput?: ElementRef<HTMLInputElement>;

    activeTab: SynthesisTab = 'image';
    prompt = '';
    negativePrompt = '';
    provider = 'core';
    imageModel = 'z_image_turbo';
    aspectRatio = '1:1';
    width = 768;
    height = 768;
    steps = 30;
    guidanceScale = 7;
    seed: number | null = null;
    sampler = 'euler';
    scheduler = 'euler';
    persistOutput = false;
    comfyuiCheckpoint = '';
    comfyuiStatus: ComfyUIStatusResponse['comfyui'] | null = null;
    comfyuiLoading = false;
    generating = false;
    importingCheckpoint = false;
    importingCheckpointPath = false;
    generatedAt: Date | null = null;
    generatedImageDataUrl: string | null = null;
    generatedProviderLabel = '';
    imageModels: SynthesisModelInfo[] = [];
    localModelsRoot = '';
    importSourcePath = '';
    importVaePath = '';
    importModelLabel = '';
    importModelId = '';
    importFamily = 'auto';

    readonly tabs: Array<{ key: SynthesisTab; label: string }> = [
        { key: 'image', label: 'synthesis.tabs.image' },
        { key: 'video', label: 'synthesis.tabs.video' },
        { key: 'audio', label: 'synthesis.tabs.audio' },
    ];

    providerOptions: Record<SynthesisTab, UiSelectOption<string>[]> = {
        image: [{ label: 'pai-image-gen', value: 'core' }],
        video: [
            { label: 'Veo 2.0 (mock)', value: 'veo_2_mock' },
            { label: 'Luma Dream Machine (mock)', value: 'luma_mock' },
            { label: 'Pika 2.0 (mock)', value: 'pika_mock' },
        ],
        audio: [
            { label: 'NeuralSynth v1 (mock)', value: 'neuralsynth_mock' },
            { label: 'AudioLDM (mock)', value: 'audioldm_mock' },
            { label: 'Bark (mock)', value: 'bark_mock' },
        ],
    };

    readonly aspectRatioOptions: UiSelectOption<string>[] = [
        { label: '1:1', value: '1:1' },
        { label: '16:9', value: '16:9' },
        { label: '9:16', value: '9:16' },
        { label: 'Custom', value: 'custom' },
    ];

    readonly fallbackSamplerOptions: UiSelectOption<string>[] = [
        { label: 'Euler', value: 'euler' },
        { label: 'Euler a', value: 'euler_a' },
        { label: 'DPM++ 2M', value: 'dpmpp_2m' },
        { label: 'DDIM', value: 'ddim' },
        { label: 'PNDM', value: 'pndm' },
        { label: 'LMS', value: 'lms' },
    ];

    readonly fallbackSchedulerOptions: UiSelectOption<string>[] = [
        { label: 'Normal', value: 'normal' },
        { label: 'Karras', value: 'karras' },
        { label: 'Exponential', value: 'exponential' },
        { label: 'Simple', value: 'simple' },
        { label: 'DDIM uniform', value: 'ddim_uniform' },
    ];

    readonly importFamilyOptions: UiSelectOption<string>[] = [
        { label: 'Auto detect', value: 'auto' },
        { label: 'Stable Diffusion checkpoint', value: 'stable-diffusion-checkpoint' },
        { label: 'SDXL checkpoint', value: 'sdxl-checkpoint' },
    ];

    constructor(
        private synthesisService: SynthesisService,
        private notificationService: NotificationService,
    ) {}

    ngOnInit(): void {
        this.loadImageModels();
        this.loadComfyUIStatus();
    }

    setTab(tab: SynthesisTab): void {
        this.activeTab = tab;
        this.provider = this.providerOptions[tab][0]?.value || '';
        if (tab === 'image' && !this.provider) {
            this.provider = 'core';
        }
        this.generatedAt = null;
        this.generatedImageDataUrl = null;
        this.generatedProviderLabel = '';
    }

    generate(): void {
        if (this.generating || !this.prompt.trim()) {
            return;
        }

        if (this.activeTab !== 'image') {
            this.generateMock();
            return;
        }

        this.generateImage();
    }

    private loadImageModels(): void {
        this.synthesisService.getModels$(true).pipe(take(1)).subscribe({
            next: (response) => {
                const models = Array.isArray(response?.models) ? response.models : [];
                if (models.length === 0) {
                    return;
                }

                this.imageModels = models;
                this.localModelsRoot = response?.local_models_root || this.localModelsRoot || 'storage/models/image-generation';
                this.updateImageProviderOptions(models);

                const coreLocal = models.find((item) => (item.provider || 'core') === 'core' && item.source === 'local');
                const defaultModel = response?.default_model;
                const selected = coreLocal?.model_id
                    || (defaultModel && models.some((item) => item.model_id === defaultModel) ? defaultModel : '')
                    || models[0]?.model_id;

                if (selected) {
                    this.imageModel = selected;
                    this.provider = models.find((item) => item.model_id === selected)?.provider || 'core';
                    this.applySelectedModelDefaults();
                }
            },
            error: () => {
                // Keep static fallback options if backend models endpoint is unavailable.
            },
        });
    }

    get imageModelOptions(): UiSelectOption<string>[] {
        return this.imageModels
            .filter((model) => (model.provider || 'core') === this.provider)
            .map((model) => ({
                value: model.model_id,
                label: this.formatModelLabel(model),
            }));
    }

    onImageProviderChange(provider: string): void {
        this.provider = provider;
        if (provider === 'comfyui' && !this.comfyuiStatus) {
            this.loadComfyUIStatus();
        }
        const options = this.imageModelOptions;
        if (!options.some((item) => item.value === this.imageModel)) {
            this.imageModel = options[0]?.value || '';
            this.applySelectedModelDefaults();
        }
    }

    get comfyuiCheckpointOptions(): UiSelectOption<string>[] {
        const checkpoints = this.comfyuiStatus?.resources?.checkpoints || [];
        return checkpoints.map((checkpoint) => ({
            value: checkpoint,
            label: checkpoint,
        }));
    }

    get comfyuiEndpointRows(): Array<{ path: string; method: string; ok?: boolean; status?: number | string; purpose?: string }> {
        const probed = new Map<string, any>();
        (this.comfyuiStatus?.probed_endpoints || []).forEach((item) => probed.set(`${item.method}:${item.path}`, item));
        return (this.comfyuiStatus?.endpoints || []).map((item) => {
            const probe = probed.get(`${item.method}:${item.path}`);
            return {
                ...item,
                ok: probe?.ok,
                status: probe?.status ?? (probe ? 'error' : 'available'),
            };
        });
    }

    loadComfyUIStatus(): void {
        if (this.comfyuiLoading) {
            return;
        }
        this.comfyuiLoading = true;
        this.synthesisService.getComfyUIStatus$().pipe(
            take(1),
            finalize(() => {
                this.comfyuiLoading = false;
            }),
        ).subscribe({
            next: (response) => {
                this.comfyuiStatus = response?.comfyui || null;
                const checkpoints = this.comfyuiStatus?.resources?.checkpoints || [];
                const configured = this.comfyuiStatus?.configured_checkpoint || '';
                if (!this.comfyuiCheckpoint) {
                    this.comfyuiCheckpoint = checkpoints.includes(configured)
                        ? configured
                        : checkpoints[0] || configured || '';
                }
                if (this.provider === 'comfyui') {
                    this.normalizeComfySamplerAndScheduler();
                }
            },
            error: (error) => {
                this.comfyuiStatus = null;
                this.notificationService.open({
                    title: 'ComfyUI',
                    type: 'error',
                    message: error?.error?.detail || 'Failed to load ComfyUI status',
                    autoClose: true,
                });
            },
        });
    }

    onImageModelChange(modelId: string): void {
        this.imageModel = modelId;
        this.applySelectedModelDefaults();
    }

    onAspectRatioChange(value: string): void {
        this.aspectRatio = value;
        if (value === '1:1') {
            this.width = 768;
            this.height = 768;
        } else if (value === '16:9') {
            this.width = 1024;
            this.height = 576;
        } else if (value === '9:16') {
            this.width = 576;
            this.height = 1024;
        }
    }

    triggerCheckpointImport(): void {
        this.checkpointInput?.nativeElement.click();
    }

    importCheckpoint(event: Event): void {
        const input = event.target as HTMLInputElement | null;
        const file = input?.files?.[0];
        if (!file || this.importingCheckpoint) {
            if (input) {
                input.value = '';
            }
            return;
        }
        this.importingCheckpoint = true;
        this.synthesisService.importCheckpoint$(file).pipe(
            finalize(() => {
                this.importingCheckpoint = false;
                if (input) {
                    input.value = '';
                }
            }),
        ).subscribe({
            next: () => {
                this.notificationService.open({
                    title: 'Checkpoint imported',
                    type: 'success',
                    message: file.name,
                    autoClose: true,
                });
                this.synthesisService.getModels$(true).pipe(take(1)).subscribe({
                    next: (response) => {
                        this.imageModels = Array.isArray(response?.models) ? response.models : [];
                        const imported = this.imageModels.find((model) => model.label === file.name.replace(/\.[^.]+$/, ''));
                        if (imported) {
                            this.provider = imported.provider || 'core';
                            this.imageModel = imported.model_id;
                            this.applySelectedModelDefaults();
                        }
                    },
                });
            },
            error: (error) => {
                this.notificationService.open({
                    title: 'Checkpoint import failed',
                    type: 'error',
                    message: error?.error?.detail || 'Failed to import checkpoint',
                    autoClose: true,
                });
            },
        });
    }

    importCheckpointFromPath(): void {
        const sourcePath = this.importSourcePath.trim();
        if (!sourcePath || this.importingCheckpointPath) {
            return;
        }
        this.importingCheckpointPath = true;
        this.synthesisService.importCheckpointFromPath$({
            sourcePath,
            label: this.importModelLabel.trim(),
            modelId: this.importModelId.trim(),
            family: this.importFamily,
            vaePath: this.importVaePath.trim(),
        }).pipe(
            finalize(() => {
                this.importingCheckpointPath = false;
            }),
        ).subscribe({
            next: (response) => {
                const imported = response?.model as SynthesisModelInfo | undefined;
                this.notificationService.open({
                    title: 'Model imported',
                    type: 'success',
                    message: imported?.label || sourcePath,
                    autoClose: true,
                });
                this.refreshImageModels(imported?.model_id);
            },
            error: (error) => {
                this.notificationService.open({
                    title: 'Model import failed',
                    type: 'error',
                    message: error?.error?.detail || 'Failed to import local model',
                    autoClose: true,
                });
            },
        });
    }

    refreshImageModels(selectModelId?: string): void {
        this.synthesisService.invalidateCache();
        this.synthesisService.getModels$(true).pipe(take(1)).subscribe({
            next: (response) => {
                this.imageModels = Array.isArray(response?.models) ? response.models : [];
                this.localModelsRoot = response?.local_models_root || this.localModelsRoot || 'storage/models/image-generation';
                this.updateImageProviderOptions(this.imageModels);
                if (selectModelId && this.imageModels.some((model) => model.model_id === selectModelId)) {
                    this.imageModel = selectModelId;
                    this.provider = this.imageModels.find((model) => model.model_id === selectModelId)?.provider || 'core';
                    this.applySelectedModelDefaults();
                }
            },
        });
    }

    private updateImageProviderOptions(models: SynthesisModelInfo[]): void {
        const providers = new Map<string, string>();
        models.forEach((model) => {
            const provider = model.provider || 'core';
            providers.set(provider, this.formatProviderLabel(provider));
        });
        this.providerOptions.image = Array.from(providers.entries()).map(([value, label]) => ({
            value,
            label,
        }));
    }

    private generateImage(): void {
        const modelError = this.getImageModelError();
        if (modelError) {
            this.notificationService.open({
                title: 'Synthesis setup issue',
                type: 'error',
                message: modelError,
                autoClose: true,
            });
            return;
        }
        this.generating = true;
        this.generatedAt = null;
        this.generatedImageDataUrl = null;

        this.synthesisService
            .generateImage$({
                prompt: this.prompt.trim(),
                provider: this.provider,
                model: this.imageModel,
                aspectRatio: this.aspectRatio,
                negativePrompt: this.negativePrompt.trim(),
                width: this.width,
                height: this.height,
                numInferenceSteps: this.steps,
                guidanceScale: this.guidanceScale,
                seed: this.seed,
                sampler: this.provider === 'comfyui' ? this.sampler : null,
                scheduler: this.scheduler,
                comfyuiCheckpoint: this.provider === 'comfyui' ? this.comfyuiCheckpoint : null,
                persistOutput: this.persistOutput,
            })
            .pipe(
                finalize(() => {
                    this.generating = false;
                }),
            )
            .subscribe({
                next: (response) => {
                    this.generatedImageDataUrl = `data:${response.mime_type};base64,${response.image_base64}`;
                    this.generatedAt = new Date();
                    const modelId = response.model_id || this.imageModel;
                    this.generatedProviderLabel = this.getImageModelLabel(modelId);
                },
                error: (error) => {
                    this.generatedAt = null;
                    this.generatedImageDataUrl = null;
                    const message = error?.error?.detail || 'Image generation failed';
                    this.notificationService.open({
                        title: 'Synthesis Error',
                        type: 'error',
                        message,
                        autoClose: true,
                    });
                },
            });
    }

    private generateMock(): void {
        this.generating = true;
        this.generatedAt = null;
        window.setTimeout(() => {
            this.generating = false;
            this.generatedAt = new Date();
            this.generatedProviderLabel = this.getProviderLabel(this.activeTab, this.provider);
        }, 1200);
    }

    private getProviderLabel(tab: SynthesisTab, value: string): string {
        return this.providerOptions[tab].find((item) => item.value === value)?.label || value;
    }

    private getImageModelLabel(value: string): string {
        return this.imageModels.find((item) => item.model_id === value)?.label || value;
    }

    private getSelectedImageModel(): SynthesisModelInfo | undefined {
        return this.imageModels.find((model) => model.model_id === this.imageModel);
    }

    get samplerOptions(): UiSelectOption<string>[] {
        const samplers = this.provider === 'comfyui'
            ? this.comfyuiStatus?.resources?.samplers || []
            : [];
        const values = samplers.length ? samplers : this.fallbackSamplerOptions.map((item) => item.value);
        return values.map((value) => ({ value, label: this.formatSamplerLabel(value) }));
    }

    get schedulerOptions(): UiSelectOption<string>[] {
        const schedulers = this.provider === 'comfyui'
            ? this.comfyuiStatus?.resources?.schedulers || []
            : [];
        const values = schedulers.length ? schedulers : this.fallbackSchedulerOptions.map((item) => item.value);
        return values.map((value) => ({ value, label: this.formatSamplerLabel(value) }));
    }

    private applySelectedModelDefaults(): void {
        const defaults = this.getSelectedImageModel()?.defaults || {};
        this.width = Number(defaults['width'] || this.width || 768);
        this.height = Number(defaults['height'] || this.height || 768);
        this.steps = Number(defaults['num_inference_steps'] || this.steps || 30);
        this.guidanceScale = Number(defaults['guidance_scale'] ?? this.guidanceScale ?? 7);
        if ((this.getSelectedImageModel()?.provider || '') === 'comfyui') {
            this.sampler = String(defaults['sampler'] || defaults['scheduler'] || this.sampler || 'euler');
            this.scheduler = String(
                defaults['comfy_scheduler']
                || defaults['scheduler_mode']
                || (this.isComfySchedulerValue(this.scheduler) ? this.scheduler : 'normal')
            );
            this.normalizeComfySamplerAndScheduler();
        } else {
            this.scheduler = String(defaults['scheduler'] || this.scheduler || 'euler');
        }
        if ((this.getSelectedImageModel()?.provider || '') === 'comfyui' && !this.comfyuiCheckpoint) {
            this.comfyuiCheckpoint = this.comfyuiStatus?.configured_checkpoint || this.comfyuiCheckpoint;
        }
        this.aspectRatio = this.width === this.height
            ? '1:1'
            : this.width > this.height
                ? '16:9'
                : '9:16';
    }

    private normalizeComfySamplerAndScheduler(): void {
        const samplers = this.comfyuiStatus?.resources?.samplers || [];
        if (samplers.length && !samplers.includes(this.sampler)) {
            this.sampler = samplers.includes('euler') ? 'euler' : samplers[0];
        }
        const schedulers = this.comfyuiStatus?.resources?.schedulers || [];
        if (schedulers.length && !schedulers.includes(this.scheduler)) {
            this.scheduler = schedulers.includes('normal') ? 'normal' : schedulers[0];
        }
    }

    private isComfySchedulerValue(value: string): boolean {
        return this.fallbackSchedulerOptions.some((item) => item.value === value);
    }

    private getImageModelError(): string {
        const model = this.getSelectedImageModel();
        if (!model || model.capabilities?.['pipeline_available'] !== false) {
            return '';
        }
        if ((model.provider || '') === 'comfyui') {
            if (model.capabilities?.['enabled'] === false) {
                return 'ComfyUI is disabled. Enable synthesis.comfyui.enabled in config.';
            }
            if (!this.comfyuiCheckpoint) {
                return 'Select a ComfyUI checkpoint.';
            }
            return '';
        }
        const required = model.capabilities?.['required_pipeline'] || 'pipeline';
        const version = model.capabilities?.['diffusers']?.['version'];
        return `${required} is unavailable${version ? ` in diffusers ${version}` : ''}`;
    }

    private formatModelLabel(model: SynthesisModelInfo): string {
        const suffixes: string[] = [];
        if (!model.installed && model.source === 'huggingface') {
            suffixes.push('built-in HF');
        }
        if (model.installed && model.source === 'local') {
            suffixes.push('local');
        }
        if (model.capabilities?.['pipeline_available'] === false) {
            suffixes.push('pipeline missing');
        }
        if (model.vae_path) {
            suffixes.push('vae');
        }
        return suffixes.length ? `${model.label} (${suffixes.join(', ')})` : model.label;
    }

    private formatProviderLabel(provider: string): string {
        const labels: Record<string, string> = {
            diffusers: 'pai-image-gen',
            core: 'pai-image-gen',
            comfyui: 'ComfyUI',
            stable_diffusion_webui: 'Stable Diffusion WebUI',
        };
        return labels[provider] || provider.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
    }

    private formatSamplerLabel(value: string): string {
        const labels: Record<string, string> = {
            euler: 'Euler',
            euler_a: 'Euler a',
            euler_ancestral: 'Euler ancestral',
            dpmpp_2m: 'DPM++ 2M',
            ddim: 'DDIM',
            lms: 'LMS',
            normal: 'Normal',
            karras: 'Karras',
            exponential: 'Exponential',
            simple: 'Simple',
            ddim_uniform: 'DDIM uniform',
        };
        return labels[value] || value;
    }
}
