import { Component, OnInit } from '@angular/core';
import { finalize, take } from 'rxjs/operators';
import { NotificationService } from '../../shared/components/notification/notification.service';
import { UiSelectOption } from '../../shared/ui/components/ui-select/ui-select.component';
import {
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
    activeTab: SynthesisTab = 'image';
    prompt = '';
    provider = 'z_image_turbo';
    aspectRatio = '1:1';
    generating = false;
    generatedAt: Date | null = null;
    generatedImageDataUrl: string | null = null;
    generatedProviderLabel = '';
    imageModels: SynthesisModelInfo[] = [];

    readonly tabs: Array<{ key: SynthesisTab; label: string }> = [
        { key: 'image', label: 'synthesis.tabs.image' },
        { key: 'video', label: 'synthesis.tabs.video' },
        { key: 'audio', label: 'synthesis.tabs.audio' },
    ];

    providerOptions: Record<SynthesisTab, UiSelectOption<string>[]> = {
        image: [{ label: 'Z-Image-Turbo (Tongyi-MAI)', value: 'z_image_turbo' }],
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
    ];

    constructor(
        private synthesisService: SynthesisService,
        private notificationService: NotificationService,
    ) {}

    ngOnInit(): void {
        this.loadImageModels();
    }

    setTab(tab: SynthesisTab): void {
        this.activeTab = tab;
        this.provider = this.providerOptions[tab][0]?.value || '';
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
        this.synthesisService.getModels$().pipe(take(1)).subscribe({
            next: (response) => {
                const models = Array.isArray(response?.models) ? response.models : [];
                if (models.length === 0) {
                    return;
                }

                this.imageModels = models;
                this.providerOptions.image = models.map((model) => ({
                    value: model.model_id,
                    label: model.installed
                        ? `${model.label}`
                        : `${model.label} (remote)`,
                }));

                const defaultModel = response?.default_model;
                const selected = defaultModel && this.providerOptions.image.some((item) => item.value === defaultModel)
                    ? defaultModel
                    : this.providerOptions.image[0]?.value;

                if (selected) {
                    this.provider = selected;
                }
            },
            error: () => {
                // Keep static fallback options if backend models endpoint is unavailable.
            },
        });
    }

    private generateImage(): void {
        this.generating = true;
        this.generatedAt = null;
        this.generatedImageDataUrl = null;

        this.synthesisService
            .generateImage$({
                prompt: this.prompt.trim(),
                model: this.provider,
                provider: this.provider,
                aspectRatio: this.aspectRatio,
                numInferenceSteps: 9,
                guidanceScale: 0.0,
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
                    const modelId = response.model_id || this.provider;
                    this.generatedProviderLabel = this.getProviderLabel('image', modelId);
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
}

