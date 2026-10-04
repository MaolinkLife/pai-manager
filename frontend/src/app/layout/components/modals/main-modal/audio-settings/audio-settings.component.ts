import { Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { pickChangedFields } from '../../../../../core/utils/changed-fields';
import { ResourcesService } from '../../../../../core/services/resources.service';
import { Observable, BehaviorSubject, combineLatest } from 'rxjs';
import { map, startWith, tap, finalize } from 'rxjs/operators';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';

interface AudioDevice {
    id: number;
    name: string;
}

interface AudioDevicesData {
    inputDevices: AudioDevice[];
}

@Component({
    selector: 'app-audio-settings',
    templateUrl: './audio-settings.component.html',
    styleUrls: ['./audio-settings.component.less'],
    standalone: false
})
export class AudioSettingsComponent implements OnInit {
    audioForm: UntypedFormGroup;
    originalConfig: any = {};
    originalModules: any = {};
    isLoading$ = new BehaviorSubject<boolean>(true);

    devices$: Observable<AudioDevicesData> = new Observable<AudioDevicesData>();
    inputDeviceOptions: UiSelectOption<number>[] = [];
    channelsOptions: UiSelectOption<number>[] = [
        { value: 1, label: 'Mono (1)' },
        { value: 2, label: 'Stereo (2)' },
    ];
    sttProviderOptions: UiSelectOption<string>[] = [
        { value: 'whisper', label: 'faster-whisper (default)' },
        { value: 'sherpa_onnx', label: 'sherpa-onnx' },
    ];
    sherpaModelTypeOptions: UiSelectOption<string>[] = [
        { value: 'transducer', label: 'Transducer (encoder/decoder/joiner)' },
        { value: 'paraformer', label: 'Paraformer' },
        { value: 'whisper', label: 'Whisper ONNX' },
        { value: 'moonshine', label: 'Moonshine' },
    ];
    sherpaDeviceOptions: UiSelectOption<string>[] = [
        { value: 'cpu', label: 'CPU' },
        { value: 'cuda', label: 'CUDA' },
    ];
    private originalSttSnapshot: any = {};
    /** Without the stored values a save could not tell what changed. */
    loadFailed = false;

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private resourcesService: ResourcesService,
        private localizationService: LocalizationService,
        private notificationService: NotificationService,
    ) {
        this.audioForm = this.createForm();
    }

    ngOnInit(): void {
        this.loadConfigAndDevices();
        this.localizationService.init();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            sttEnabled: [false],
            inputDeviceId: [0],
            sampleRate: [16000],
            channels: [1],
            chunkSize: [1024],
            enableVad: [true],
            vadThreshold: [0.5],
            silenceTimeout: [3.0],
            minAudioLength: [0.5],
            maxAudioLength: [30.0],
            triggerWords: [[]],
            ignoreTriggerWords: [true],
            // STT block (0.7.2)
            stt: this.fb.group({
                language: ['en-US'],
                autoDetect: [false],
                provider: ['whisper'],
                sherpaOnnx: this.fb.group({
                    modelType: ['transducer'],
                    encoder: [''],
                    decoder: [''],
                    joiner: [''],
                    paraformer: [''],
                    whisperEncoder: [''],
                    whisperDecoder: [''],
                    moonshinePreprocessor: [''],
                    moonshineEncoder: [''],
                    moonshineUncachedDecoder: [''],
                    moonshineCachedDecoder: [''],
                    tokens: [''],
                    numThreads: [1],
                    provider: ['cpu'],
                }),
            }),
        });
    }

    get sttProvider(): string {
        return String(this.audioForm.get('stt.provider')?.value || 'whisper');
    }

    get sherpaModelType(): string {
        return String(this.audioForm.get('stt.sherpaOnnx.modelType')?.value || 'transducer');
    }

    private patchSttSection(stt: any): void {
        const s = stt || {};
        const sherpa = s.sherpaOnnx || s.sherpa_onnx || {};
        this.audioForm.get('stt')!.patchValue({
            language: s.language ?? 'en-US',
            autoDetect: s.autoDetect ?? s.auto_detect ?? false,
            provider: s.provider ?? 'whisper',
            sherpaOnnx: {
                modelType: sherpa.modelType ?? sherpa.model_type ?? 'transducer',
                encoder: sherpa.encoder ?? '',
                decoder: sherpa.decoder ?? '',
                joiner: sherpa.joiner ?? '',
                paraformer: sherpa.paraformer ?? '',
                whisperEncoder: sherpa.whisperEncoder ?? sherpa.whisper_encoder ?? '',
                whisperDecoder: sherpa.whisperDecoder ?? sherpa.whisper_decoder ?? '',
                moonshinePreprocessor:
                    sherpa.moonshinePreprocessor ?? sherpa.moonshine_preprocessor ?? '',
                moonshineEncoder:
                    sherpa.moonshineEncoder ?? sherpa.moonshine_encoder ?? '',
                moonshineUncachedDecoder:
                    sherpa.moonshineUncachedDecoder ?? sherpa.moonshine_uncached_decoder ?? '',
                moonshineCachedDecoder:
                    sherpa.moonshineCachedDecoder ?? sherpa.moonshine_cached_decoder ?? '',
                tokens: sherpa.tokens ?? '',
                numThreads: sherpa.numThreads ?? sherpa.num_threads ?? 1,
                provider: sherpa.provider ?? 'cpu',
            },
        });
        this.originalSttSnapshot = JSON.parse(JSON.stringify(this.audioForm.get('stt')!.value));
    }

    private buildSttPayload(): any {
        return JSON.parse(JSON.stringify(this.audioForm.get('stt')!.value));
    }

    private loadConfigAndDevices(): void {
        combineLatest([
            this.configService.getConfig$(),
            this.resourcesService.getAudioDevices$()
        ]).pipe(
            tap(() => this.isLoading$.next(true)),
            map(([config, devices]) => {
                this.loadFailed = !config;
                this.originalModules = this.normalizeModulesPayload(config?.modules);
                // Load config
                if (config && config.audio) {
                    this.audioForm.patchValue({
                        ...this.normalizeAudioPayload(config.audio),
                        sttEnabled: this.originalModules.whisper,
                    });
                } else {
                    this.audioForm.patchValue({
                        sttEnabled: this.originalModules.whisper,
                    });
                }
                // A save compares with the form as loaded, so it sends only what was edited.
                this.originalConfig = this.normalizeAudioPayload(this.audioForm.value);

                // STT block (0.7.2)
                this.patchSttSection((config as any)?.stt);

                // Load devices
                const inputDevices: AudioDevice[] = [
                    { id: 0, name: 'Default Device' },
                    ...(devices.recording_devices || []).map(
                        ([id, name]: [number, string]) => ({ id, name })
                    )
                ];

                return { inputDevices };
            }),
            finalize(() => this.isLoading$.next(false))
        ).subscribe(devicesData => {
            this.devices$ = new Observable<AudioDevicesData>(subscriber => {
                subscriber.next(devicesData);
                subscriber.complete();
            });
            this.inputDeviceOptions = devicesData.inputDevices.map((device) => ({
                value: device.id,
                label: `[${device.id}]: ${device.name}`,
            }));
        });
    }

    saveChanges(): void {
        if (!this.hasChanges()) {
            return;
        }
        const normalized = this.normalizeAudioPayload(this.audioForm.value);
        const modules = this.buildModulesPayload();
        const sttPayload = this.buildSttPayload();
        const changes = this.collectChanges(normalized, modules, sttPayload);
        this.configService.updateConfig$(changes).subscribe({
            next: (response) => {
                console.log('Audio settings updated:', response);
                this.originalConfig = normalized;
                this.originalModules = modules;
                this.originalSttSnapshot = sttPayload;
                this.notificationService.open({
                    title: 'Success',
                    type: 'success',
                    message: 'Audio settings updated successfully',
                    autoClose: true,
                });
            },
            error: (error) => {
                console.error('Error updating audio settings:', error);
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to update audio settings',
                    autoClose: true,
                });
            }
        });
    }

    hasChanges(): boolean {
        if (this.loadFailed) {
            return false;
        }
        const changes = this.collectChanges(
            this.normalizeAudioPayload(this.audioForm.value),
            this.buildModulesPayload(),
            this.buildSttPayload(),
        );
        return Object.keys(changes).length > 0;
    }

    /** Only the fields that differ from what the tab loaded, per config section. */
    private collectChanges(audio: any, modules: any, stt: any): Record<string, unknown> {
        const changes: Record<string, unknown> = {};
        const sections: Array<[string, Record<string, unknown>]> = [
            ['audio', pickChangedFields(audio, this.originalConfig)],
            ['modules', pickChangedFields(modules, this.originalModules)],
            ['stt', pickChangedFields(stt, this.originalSttSnapshot)],
        ];
        sections.forEach(([key, diff]) => {
            if (Object.keys(diff).length > 0) {
                changes[key] = diff;
            }
        });
        return changes;
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
            rag: !!source.rag,
            visual: !!source.visual,
        };
    }

    private buildModulesPayload(): any {
        return {
            ...this.originalModules,
            whisper: !!this.audioForm.get('sttEnabled')?.value,
        };
    }

    private normalizeAudioPayload(source: any): any {
        const toNumber = (value: any, fallback: number) => {
            if (value === null || value === undefined || value === '') {
                return fallback;
            }
            const num = Number(value);
            return Number.isFinite(num) ? num : fallback;
        };

        return {
            inputDeviceId: toNumber(source?.inputDeviceId, 0),
            sampleRate: toNumber(source?.sampleRate, 16000),
            channels: toNumber(source?.channels, 1),
            chunkSize: toNumber(source?.chunkSize, 1024),
            enableVad: !!source?.enableVad,
            vadThreshold: Number(source?.vadThreshold ?? 0.5),
            silenceTimeout: Number(source?.silenceTimeout ?? 3.0),
            minAudioLength: Number(source?.minAudioLength ?? 0.5),
            maxAudioLength: Number(source?.maxAudioLength ?? 30.0),
            triggerWords: Array.isArray(source?.triggerWords) ? source.triggerWords : [],
            ignoreTriggerWords: source?.ignoreTriggerWords ?? true,
        };
    }
}
