import { Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
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
    styleUrls: ['./audio-settings.component.less']
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
            ignoreTriggerWords: [true]
        });
    }

    private loadConfigAndDevices(): void {
        combineLatest([
            this.configService.getConfig$(),
            this.resourcesService.getAudioDevices$()
        ]).pipe(
            tap(() => this.isLoading$.next(true)),
            map(([config, devices]) => {
                this.originalModules = this.normalizeModulesPayload(config?.modules);
                // Load config
                if (config && config.audio) {
                    this.originalConfig = this.normalizeAudioPayload(config.audio);
                    this.audioForm.patchValue({
                        ...this.originalConfig,
                        sttEnabled: this.originalModules.whisper,
                    });
                } else {
                    this.audioForm.patchValue({
                        sttEnabled: this.originalModules.whisper,
                    });
                }

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
        const normalized = this.normalizeAudioPayload(this.audioForm.value);
        const modules = this.buildModulesPayload();
        const updateData: any = {};
        if (this.hasPayloadChanged(normalized)) {
            updateData.audio = normalized;
        }
        if (JSON.stringify(modules) !== JSON.stringify(this.originalModules)) {
            updateData.modules = modules;
        }
        if (Object.keys(updateData).length > 0) {
            this.configService.updateConfig$(updateData).subscribe({
                next: (response) => {
                    console.log('Audio settings updated:', response);
                    this.originalConfig = normalized;
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
    }

    private hasPayloadChanged(current: any): boolean {
        return JSON.stringify(current) !== JSON.stringify(this.originalConfig);
    }

    hasChanges(): boolean {
        const normalized = this.normalizeAudioPayload(this.audioForm.value);
        const modules = this.buildModulesPayload();
        return (
            this.hasPayloadChanged(normalized) ||
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
