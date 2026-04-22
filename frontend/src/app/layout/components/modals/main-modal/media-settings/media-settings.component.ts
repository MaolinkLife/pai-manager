import { ChangeDetectorRef, Component, OnDestroy, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { UiNotificationService } from '../../../../../shared/ui/services/ui-notification.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';
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
    readonly stylePresetOptions: UiSelectOption[] = [
        { value: 'anime', label: 'Anime' },
        { value: 'semi_real_anime', label: 'Semi-real anime' },
        { value: 'illustration', label: 'Illustration' },
    ];
    readonly renderProfileOptions: UiSelectOption[] = [
        { value: 'default_anime', label: 'Default anime' },
        { value: 'portrait_soft', label: 'Portrait soft' },
        { value: 'cozy_home', label: 'Cozy home' },
    ];
    private readonly destroy$ = new Subject<void>();

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private uiNotificationService: UiNotificationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.mediaForm = this.createForm();
    }

    ngOnInit(): void {
        this.loadConfig();
    }

    ngOnDestroy(): void {
        this.destroy$.next();
        this.destroy$.complete();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
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
            }),
            diffusers: this.fb.group({
                enabled: [true],
                device: ['auto'],
                default_model: ['z_image_turbo'],
                local_models_path: [''],
                cache_dir: [''],
                torch_dtype: ['auto'],
            }),
            prompting: this.fb.group({
                enabled: [true],
                max_attempts: [3],
                assess_enabled: [true],
                quality_threshold: [0.72],
                appearance_prompt: [''],
                default_negative_prompt: ['(text:2), (signature:2), raw photo'],
                visual_profile: this.fb.group({
                    character_name: ['PAI'],
                    appearance_textarea: [''],
                    default_outfit: [''],
                    default_environment: [''],
                    style_preset: ['anime'],
                    render_profile: ['default_anime'],
                    selfie_bias: [0.85],
                    environment_bias: [0.10],
                    symbolic_bias: [0.05],
                    anti_repetition_strength: [0.65],
                    use_time_of_day: [true],
                    use_season: [true],
                    use_weather: [true],
                    use_relation_state: [true],
                    use_recent_topics: [true],
                    selfie_composition_base: [''],
                    selfie_composition_pool_override: [''],
                    environment_composition_pool_override: [''],
                    allow_self_images: [true],
                    allow_environment_images: [true],
                    allow_symbolic_images: [true],
                }),
            }),
        });
    }

    private loadConfig(): void {
        this.configService.getConfig$()
            .pipe(takeUntil(this.destroy$))
            .subscribe({
                next: (config: any) => {
                    const synthesis = config?.synthesis || {};
                    this.mediaForm.patchValue({
                        sd_webui: synthesis.sd_webui || {},
                        comfyui: synthesis.comfyui || {},
                        diffusers: synthesis.diffusers || {},
                        prompting: {
                            ...(synthesis.prompting || {}),
                            visual_profile: {
                                ...(synthesis.prompting?.visual_profile || {}),
                            },
                        },
                    });
                    this.originalSynthesis = this.mediaForm.value;
                    this.cdr.markForCheck();
                },
                error: () => {
                    this.cdr.markForCheck();
                },
            });
    }

    saveChanges(): void {
        const synthesis = this.mediaForm.value;
        if (JSON.stringify(synthesis) === JSON.stringify(this.originalSynthesis)) {
            return;
        }
        this.configService.updateConfig$({ synthesis }).pipe(takeUntil(this.destroy$)).subscribe({
            next: () => {
                this.originalSynthesis = synthesis;
                this.uiNotificationService.success('Media generation settings updated', 'Settings');
                this.cdr.markForCheck();
            },
            error: (error) => {
                console.error('Media settings update error:', error);
                this.uiNotificationService.error('Failed to update media settings', 'Settings');
                this.cdr.markForCheck();
            }
        });
    }

    hasChanges(): boolean {
        return JSON.stringify(this.mediaForm.value) !== JSON.stringify(this.originalSynthesis);
    }
}
