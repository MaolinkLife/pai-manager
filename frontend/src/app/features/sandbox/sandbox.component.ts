import { Component, OnInit } from '@angular/core';
import { finalize, take } from 'rxjs/operators';
import { ProjectConfig } from '../../core/models/project-config.model';
import { ApiService, SandboxCase, SandboxPipelineResponse } from '../../core/services/api.service';
import { ConfigService } from '../../core/services/config.service';
import {
    ComfyUIStatusResponse,
    SynthesisModelInfo,
    SynthesisService,
} from '../../core/services/synthesis.service';
import { NotificationService } from '../../shared/components/notification/notification.service';
import { UiSelectOption } from '../../shared/ui/components/ui-select/ui-select.component';

function generateTempId(): string {
    if ((crypto as any).randomUUID) {
        return (crypto as any).randomUUID();
    }
    return 'temp-' + Math.random().toString(36).slice(2, 10);
}

type SandboxMode = 'text' | 'image' | 'vision';

interface SandboxMessage {
    role: 'user' | 'assistant' | 'system';
    content: string;
    timestamp: string;
    provider?: string;
    model?: string;
    elapsedMs?: number;
    reasoning?: string;
    media?: any[];
    imagePrompt?: string;
    imageParameters?: Record<string, any>;
}

interface SandboxTraceView {
    stage: string;
    state: string;
    elapsedMs?: number;
    meta?: string;
    details?: Record<string, any>;
}

@Component({
    selector: 'app-sandbox',
    templateUrl: './sandbox.component.html',
    styleUrls: ['./sandbox.component.less'],
})
export class SandboxComponent implements OnInit {
    mode: SandboxMode = 'text';
    pipelineMode: 'direct' | 'full' = 'direct';
    provider = 'ollama';
    model = '';
    systemPrompt = 'You are a precise sandbox assistant. Follow the system prompt and answer only this isolated test request.';
    userPrompt = '';
    temperature = 0.85;
    topP = 0.9;
    topK = 50;
    maxTokens = 1024;
    imageProvider = 'core';
    imageModel = '';
    imageNegativePrompt = '';
    imagePromptPolicy = '';
    imageStylePrompt = '';
    usePromptBuilder = true;
    imageWidth = 768;
    imageHeight = 768;
    imageSteps = 30;
    imageGuidanceScale = 7;
    imageSeed: number | null = null;
    imageScheduler = 'euler';
    imageComfyScheduler = 'normal';
    comfyuiCheckpoint = '';
    useUnifiedRouter = true;
    persistOutput = false;
    loading = false;
    providerOptions: UiSelectOption[] = [];
    modelOptions: string[] = [];
    imageProviderOptions: UiSelectOption<string>[] = [];
    imageModels: SynthesisModelInfo[] = [];
    comfyuiStatus: ComfyUIStatusResponse['comfyui'] | null = null;
    testCases: SandboxCase[] = [];
    caseOptions: UiSelectOption[] = [];
    selectedCaseId = '';
    mediaAttachments: any[] = [];
    messages: SandboxMessage[] = [];
    lastResponse: SandboxPipelineResponse | null = null;
    traces: SandboxTraceView[] = [];
    private config: ProjectConfig | null = null;

    readonly modeOptions: UiSelectOption<SandboxMode>[] = [
        { value: 'text', label: 'Text' },
        { value: 'image', label: 'Image generation' },
        { value: 'vision', label: 'Vision describe' },
    ];
    readonly pipelineModeOptions: UiSelectOption<'direct' | 'full'>[] = [
        { value: 'direct', label: 'Direct: input -> instructor -> LLM' },
        { value: 'full', label: 'Full: Decision Layer pipeline' },
    ];

    constructor(
        private apiService: ApiService,
        private configService: ConfigService,
        private synthesisService: SynthesisService,
        private notificationService: NotificationService,
    ) {}

    ngOnInit(): void {
        this.configService.getConfig$().subscribe({
            next: (config) => {
                this.config = config;
                const providers = config?.api?.providers || {};
                this.providerOptions = Object.keys(providers).map((key) => ({
                    value: key,
                    label: this.formatProviderLabel(key),
                }));
                this.provider = config?.api?.activeProvider || this.providerOptions[0]?.value || 'ollama';
                this.imageProvider = this.getPreferredImageProvider(config);
                this.applyImageProviderDefaults(this.imageProvider);
                if (this.imageModels.length) {
                    this.imageModel = this.getImageModelForProvider(this.imageProvider);
                    this.applySelectedImageModelDefaults();
                }
                this.applyProviderDefaults(this.provider);
            },
            error: () => {
                this.notificationService.open({
                    type: 'error',
                    title: 'Sandbox config unavailable',
                    autoClose: true,
                });
            },
        });
        this.apiService.getSandboxCases$().subscribe((cases) => {
            this.testCases = cases;
            this.caseOptions = cases.map((item) => ({ value: item.id, label: item.title }));
        });
        this.loadImageModels();
        this.loadComfyUIStatus();
    }

    onProviderChange(provider: string): void {
        this.provider = provider;
        this.applyProviderDefaults(provider);
    }

    run(): void {
        const prompt = this.userPrompt.trim();
        if (!prompt || this.loading) {
            return;
        }
        this.messages.push({
            role: 'user',
            content: prompt,
            timestamp: new Date().toISOString(),
        });
        this.loading = true;
        this.lastResponse = null;

        this.traces = [];
        const imageModel = this.getImageModelForProvider(this.imageProvider);
        const commonPayload = {
            provider: this.provider,
            model: this.model,
            system_prompt: this.systemPrompt,
            user_prompt: prompt,
            temperature: Number(this.temperature),
            top_p: Number(this.topP),
            top_k: Number(this.topK),
            max_tokens: Number(this.maxTokens),
            media: this.mediaAttachments,
            case_id: this.selectedCaseId,
        };
        const request$ = this.mode === 'image'
            ? this.apiService.sandboxImagePipeline$({
                mode: 'image',
                ...commonPayload,
                image_provider: this.imageProvider,
                image_model: imageModel,
                image_negative_prompt: this.imageNegativePrompt,
                width: Number(this.imageWidth),
                height: Number(this.imageHeight),
                num_inference_steps: Number(this.imageSteps),
                guidance_scale: Number(this.imageGuidanceScale),
                seed: this.imageSeed === null || this.imageSeed === undefined ? null : Number(this.imageSeed),
                sampler: this.imageProvider === 'comfyui' ? this.imageScheduler : null,
                scheduler: this.imageProvider === 'comfyui' ? this.imageComfyScheduler : this.imageScheduler,
                comfyui_checkpoint: this.imageProvider === 'comfyui' ? this.comfyuiCheckpoint : null,
                use_unified_router: this.useUnifiedRouter,
                use_prompt_builder: this.usePromptBuilder,
                image_prompt_policy: this.imagePromptPolicy,
                image_style_prompt: this.imageStylePrompt,
                persist_output: this.persistOutput,
            })
            : this.mode === 'vision'
                ? this.apiService.sandboxVision$({
                    mode: 'vision',
                    ...commonPayload,
                })
                : this.apiService.sandboxPipelineTest$({
                mode: this.pipelineMode,
                ...commonPayload,
            });

        request$
            .pipe(finalize(() => (this.loading = false)))
            .subscribe({
                next: (response) => {
                    this.lastResponse = response;
                    this.traces = this.mapTraces(response.traces || []);
                    const content = this.mode === 'image'
                        ? this.buildImagePipelineMessage(response)
                        : response.content || '';
                    this.messages.push({
                        role: 'assistant',
                        content,
                        timestamp: new Date().toISOString(),
                        provider: response.provider,
                        model: response.model,
                        elapsedMs: response.elapsed_ms,
                        reasoning: response.reasoning,
                        media: response.media || [],
                        imagePrompt: response.image_prompt,
                        imageParameters: response.image_parameters,
                    });
                },
                error: (error) => {
                    const detail = error?.error?.detail || error?.message || 'Sandbox request failed';
                    this.notificationService.open({
                        type: 'error',
                        title: String(detail),
                        autoClose: true,
                    });
                },
            });
    }

    clear(): void {
        this.messages = [];
        this.lastResponse = null;
        this.traces = [];
    }

    copyLast(): void {
        if (!this.lastResponse?.content) {
            return;
        }
        navigator.clipboard?.writeText(this.lastResponse.content);
        this.notificationService.open({
            type: 'success',
            title: 'Copied',
            autoClose: true,
        });
    }

    getRunDisabled(): boolean {
        return this.loading || !this.userPrompt.trim();
    }

    applyCase(caseId: string): void {
        this.selectedCaseId = caseId;
        const selected = this.testCases.find((item) => item.id === caseId);
        if (!selected) {
            return;
        }
        this.userPrompt = selected.prompt;
        this.pipelineMode = selected.requires?.length ? 'full' : 'direct';
        if (selected.requires?.includes('image_generation')) {
            this.mode = 'image';
        } else if (selected.requires?.includes('vision')) {
            this.mode = 'vision';
        }
    }

    onImageFileSelected(event: Event): void {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) {
            return;
        }
        const reader = new FileReader();
        reader.onload = () => {
            const raw = String(reader.result || '');
            const base64 = raw.includes(',') ? raw.split(',', 2)[1] : raw;
            this.mediaAttachments = [{
                id: generateTempId(),
                name: file.name,
                mimeType: file.type || 'application/octet-stream',
                category: file.type.startsWith('image/') ? 'image' : 'document',
                size: file.size,
                data: base64,
            }];
            this.notificationService.open({ type: 'success', title: 'Media attached', autoClose: true });
        };
        reader.readAsDataURL(file);
        input.value = '';
    }

    clearMedia(): void {
        this.mediaAttachments = [];
    }

    onAudioFileSelected(event: Event): void {
        const input = event.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file || this.loading) {
            return;
        }
        this.loading = true;
        this.apiService.sandboxTranscribe$(file)
            .pipe(finalize(() => {
                this.loading = false;
                input.value = '';
            }))
            .subscribe({
                next: (response) => {
                    this.userPrompt = response.transcript || '';
                    this.selectedCaseId = 'voice_transcript';
                    this.pipelineMode = 'full';
                    this.notificationService.open({
                        type: 'success',
                        title: `Transcribed${response.elapsed_ms ? ` • ${response.elapsed_ms}ms` : ''}`,
                        autoClose: true,
                    });
                },
                error: (error) => {
                    const detail = error?.error?.detail || error?.message || 'Transcription failed';
                    this.notificationService.open({ type: 'error', title: String(detail), autoClose: true });
                },
            });
    }

    formatTimestamp(value: string): string {
        return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    trackByMessage(index: number): string {
        return String(index);
    }

    trackByTrace(index: number): string {
        return String(index);
    }

    getToolContext(): Array<{ name: string; content: string }> {
        const raw = this.lastResponse?.metadata?.['tool_context'];
        if (!Array.isArray(raw)) {
            return [];
        }
        return raw
            .filter((item) => item && typeof item === 'object')
            .map((item) => ({
                name: String(item.name || item.toolName || 'tool'),
                content: String(item.content || ''),
            }));
    }

    getImageParameters(): Array<{ key: string; value: string }> {
        const params = this.lastResponse?.image_parameters || {};
        return Object.keys(params).map((key) => ({
            key,
            value: this.formatProcessValue(params[key]),
        }));
    }

    getPromptBuilderRaw(): string {
        if (this.lastResponse?.metadata?.['prompt_builder_json_parsed']) {
            return '';
        }
        return String(
            this.lastResponse?.metadata?.['prompt_builder_raw']
            || this.lastResponse?.metadata?.['prompt_builder_reasoning']
            || '',
        ).trim();
    }

    getResultImageUrl(): string {
        const media = this.lastResponse?.media || [];
        const image = media.find((item) => item?.category === 'image' && item?.data);
        if (!image) {
            return '';
        }
        return `data:${image.mimeType || 'image/png'};base64,${image.data}`;
    }

    formatProcessValue(value: any): string {
        if (value === null || value === undefined || value === '') {
            return '-';
        }
        if (typeof value === 'object') {
            return JSON.stringify(value);
        }
        return String(value);
    }

    onImageProviderChange(provider: string): void {
        this.imageProvider = provider;
        this.imageModel = this.getImageModelForProvider(provider);
        this.applySelectedImageModelDefaults();
    }

    onImageModelChange(modelId: string): void {
        this.imageModel = modelId;
        this.applySelectedImageModelDefaults();
    }

    get imageModelOptions(): UiSelectOption<string>[] {
        return this.imageModels
            .filter((model) => (model.provider || 'diffusers') === this.imageProvider)
            .map((model) => ({
                value: model.model_id,
                label: model.label,
            }));
    }

    get comfyuiCheckpointOptions(): UiSelectOption<string>[] {
        return (this.comfyuiStatus?.resources?.checkpoints || []).map((checkpoint) => ({
            value: checkpoint,
            label: checkpoint,
        }));
    }

    get schedulerOptions(): UiSelectOption<string>[] {
        const comfySamplers = this.comfyuiStatus?.resources?.samplers || [];
        const values = comfySamplers.length ? comfySamplers : ['euler', 'euler_a', 'dpmpp_2m', 'ddim', 'lms'];
        return values.map((value) => ({ value, label: value }));
    }

    private mapTraces(traces: SandboxPipelineResponse['traces']): SandboxTraceView[] {
        return (traces || []).map((trace) => ({
            stage: trace.stage || 'unknown',
            state: trace.state || 'info',
            elapsedMs: typeof trace.elapsed_ms === 'number' ? trace.elapsed_ms : undefined,
            meta: this.formatTraceMeta(trace.details),
            details: trace.details,
        }));
    }

    private loadImageModels(): void {
        this.synthesisService.getModels$().pipe(take(1)).subscribe({
            next: (response) => {
                const models = Array.isArray(response?.models) ? response.models : [];
                this.imageModels = models;
                const providers = new Map<string, string>();
                models.forEach((model) => {
                    const provider = model.provider || 'diffusers';
                    providers.set(provider, this.formatImageProviderLabel(provider));
                });
                this.imageProviderOptions = Array.from(providers.entries()).map(([value, label]) => ({ value, label }));
                if (!this.imageProviderOptions.length) {
                    this.imageProviderOptions = [{ value: 'comfyui', label: 'ComfyUI' }];
                }
                const selected = response?.default_model && models.some((item) => item.model_id === response.default_model)
                    ? response.default_model
                    : models[0]?.model_id;
                if (selected) {
                    this.imageModel = selected;
                    this.imageProvider = models.find((item) => item.model_id === selected)?.provider || this.imageProvider;
                    const preferredProvider = this.getPreferredImageProvider(this.config);
                    if (this.imageProviderOptions.some((item) => item.value === preferredProvider)) {
                        this.imageProvider = preferredProvider;
                        this.imageModel = this.getImageModelForProvider(preferredProvider);
                    }
                    this.applySelectedImageModelDefaults();
                }
            },
            error: () => {
                this.imageProviderOptions = [{ value: 'comfyui', label: 'ComfyUI' }];
            },
        });
    }

    private loadComfyUIStatus(): void {
        this.synthesisService.getComfyUIStatus$().pipe(take(1)).subscribe({
            next: (response) => {
                this.comfyuiStatus = response?.comfyui || null;
                const checkpoints = this.comfyuiStatus?.resources?.checkpoints || [];
                const configured = this.comfyuiStatus?.configured_checkpoint || '';
                this.comfyuiCheckpoint = checkpoints.includes(configured)
                    ? configured
                    : checkpoints[0] || configured || this.comfyuiCheckpoint;
            },
            error: () => {
                this.comfyuiStatus = null;
            },
        });
    }

    private applySelectedImageModelDefaults(): void {
        const model = this.imageModels.find((item) => item.model_id === this.imageModel);
        const defaults = model?.defaults || {};
        this.imageWidth = Number(defaults['width'] || this.imageWidth || 768);
        this.imageHeight = Number(defaults['height'] || this.imageHeight || 768);
        this.imageSteps = Number(defaults['num_inference_steps'] || this.imageSteps || 30);
        this.imageGuidanceScale = Number(defaults['guidance_scale'] ?? this.imageGuidanceScale ?? 7);
        this.imageScheduler = String(defaults['scheduler'] || this.imageScheduler || 'euler');
        this.applyImageProviderDefaults(this.imageProvider);
    }

    private applyImageProviderDefaults(provider: string): void {
        const normalized = String(provider || '').trim().toLowerCase();
        if (normalized === 'comfyui') {
            const comfyui = this.config?.synthesis?.comfyui;
            if (!comfyui) {
                return;
            }
            this.imageWidth = Number(comfyui.width || this.imageWidth || 1024);
            this.imageHeight = Number(comfyui.height || this.imageHeight || 1024);
            this.imageSteps = Number(comfyui.steps || this.imageSteps || 30);
            this.imageGuidanceScale = Number(comfyui.cfg ?? this.imageGuidanceScale ?? 7);
            this.imageScheduler = String(comfyui.sampler || this.imageScheduler || 'euler');
            this.imageComfyScheduler = String(comfyui.scheduler || this.imageComfyScheduler || 'normal');
            return;
        }
        if (normalized === 'stable_diffusion_webui') {
            const sdWebui = this.config?.synthesis?.sd_webui;
            if (!sdWebui) {
                return;
            }
            this.imageGuidanceScale = Number(sdWebui.cfg_scale_default ?? this.imageGuidanceScale ?? 7);
            this.imageScheduler = String(sdWebui.sampler_name || this.imageScheduler || 'DPM++ 2M');
            this.imageComfyScheduler = String(sdWebui.scheduler || this.imageComfyScheduler || 'Automatic');
        }
    }

    private getImageModelForProvider(provider: string): string {
        const normalizedProvider = String(provider || '').trim().toLowerCase();
        const currentModel = this.imageModels.find((item) => item.model_id === this.imageModel);
        if (currentModel && (currentModel.provider || 'diffusers') === normalizedProvider) {
            return currentModel.model_id;
        }

        const providerModel = this.imageModels.find((item) => (item.provider || 'diffusers') === normalizedProvider);
        return providerModel?.model_id || '';
    }

    private getPreferredImageProvider(config: ProjectConfig | null): string {
        if (config?.synthesis?.comfyui?.enabled) {
            return 'comfyui';
        }
        if (config?.synthesis?.sd_webui?.enabled) {
            return 'stable_diffusion_webui';
        }
        return 'diffusers';
    }

    private buildImagePipelineMessage(response: SandboxPipelineResponse): string {
        const params = response.image_parameters || {};
        const blocks = [
            response.content || 'Image generated.',
            '',
            '**Image prompt**',
            response.image_prompt || '',
        ];
        if (response.negative_prompt) {
            blocks.push('', '**Negative prompt**', response.negative_prompt);
        }
        blocks.push('', '**Parameters**', '```json', JSON.stringify(params, null, 2), '```');
        if (response.vision_description) {
            blocks.push('', '**Vision description**', response.vision_description);
        }
        return blocks.join('\n');
    }

    private formatImageProviderLabel(provider: string): string {
        const labels: Record<string, string> = {
            diffusers: 'Core',
            comfyui: 'ComfyUI',
            stable_diffusion_webui: 'Stable Diffusion WebUI',
        };
        return labels[provider] || provider.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
    }

    private formatTraceMeta(details?: Record<string, any>): string | undefined {
        if (!details) {
            return undefined;
        }
        const usage = typeof details['usage'] === 'object' ? details['usage'] : {};
        const tokens = usage?.total_tokens ?? usage?.eval_count ?? usage?.completion_tokens ?? usage?.response_tokens;
        const parts: string[] = [];
        if (tokens !== undefined && tokens !== null && tokens !== '') {
            parts.push(`${tokens} tok`);
        }
        if (details['provider']) {
            parts.push(String(details['provider']));
        }
        if (details['model']) {
            parts.push(String(details['model']));
        }
        if (details['bytes']) {
            const mb = Number(details['bytes']) / (1024 * 1024);
            parts.push(mb >= 0.1 ? `${mb.toFixed(1)} MB` : `${details['bytes']} B`);
        }
        if (details['count']) {
            parts.push(`${details['count']} tasks`);
        }
        return parts.length ? parts.join(' • ') : undefined;
    }

    private applyProviderDefaults(provider: string): void {
        const providerConfig: Record<string, any> = this.config?.api?.providers?.[provider] || {};
        this.model = providerConfig.model || '';
        this.temperature = Number(providerConfig.temperature ?? this.config?.generateSettings?.temperature ?? 0.85);
        this.topP = Number(providerConfig.top_p ?? this.config?.generateSettings?.topP ?? 0.9);
        this.topK = Number(providerConfig.top_k ?? this.config?.generateSettings?.topK ?? 50);
        this.maxTokens = Number(providerConfig.maxTokens ?? this.config?.generateSettings?.numPredict ?? 1024);

        if (provider === 'ollama') {
            this.apiService.getOllamaModels$().subscribe((models) => {
                const modelSet = new Set(models || []);
                if (this.model) {
                    modelSet.add(this.model);
                }
                this.modelOptions = Array.from(modelSet);
            });
            return;
        }

        this.modelOptions = this.model ? [this.model] : [];
    }

    private formatProviderLabel(provider: string): string {
        const labels: Record<string, string> = {
            ollama: 'Ollama',
            openrouter: 'OpenRouter',
            transformers: 'Transformers',
        };
        return labels[provider] || provider.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
    }
}
