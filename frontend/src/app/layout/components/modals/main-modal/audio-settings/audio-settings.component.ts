import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { ResourcesService } from '../../../../../core/services/resources.service';
import { Observable } from 'rxjs';
import { map, startWith } from 'rxjs/operators';

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
    audioForm: FormGroup;
    originalConfig: any = {};

    devices$: Observable<AudioDevicesData> = new Observable<AudioDevicesData>();

    constructor(
        private fb: FormBuilder,
        private configService: ConfigService,
        private resourcesService: ResourcesService
    ) {
        this.audioForm = this.createForm();
    }

    ngOnInit(): void {
        this.loadConfig();
        this.loadDevices();
    }

    private createForm(): FormGroup {
        return this.fb.group({
            inputDeviceId: [0],
            sampleRate: [16000],
            channels: [1],
            chunkSize: [1024],
            enableVad: [true],
            vadThreshold: [0.5],
            silenceTimeout: [3.0],
            minAudioLength: [0.5],
            maxAudioLength: [30.0]
        });
    }

    private loadConfig(): void {
        this.configService.getConfig$().subscribe(config => {
            if (config && config.audio) {
                this.originalConfig = { ...config.audio };
                this.audioForm.patchValue(config.audio);
            }
        });
    }

    private loadDevices(): void {
        this.devices$ = this.resourcesService.getAudioDevices$().pipe(
            map((devices: any) => {
                const inputDevices: AudioDevice[] = [
                    { id: 0, name: 'Default Device' },
                    ...(devices.recording_devices || []).map(
                        ([id, name]: [number, string]) => ({ id, name })
                    )
                ];

                return { inputDevices };
            }),
            startWith({
                inputDevices: [{ id: 0, name: 'Loading...' }]
            })
        );
    }

    saveChanges(): void {
        const changes = this.getChanges();
        if (Object.keys(changes).length > 0) {
            const updateData = { audio: changes };
            this.configService.updateCongif$(updateData).subscribe({
                next: (response) => {
                    console.log('Audio settings updated:', response);
                    this.originalConfig = { ...this.audioForm.value };
                },
                error: (error) => {
                    console.error('Error updating audio settings:', error);
                }
            });
        }
    }

    private getChanges(): any {
        const current = this.audioForm.value;
        const changes: any = {};

        Object.keys(current).forEach(key => {
            const originalValue = this.originalConfig ? this.originalConfig[key] : undefined;
            if (current[key] !== originalValue) {
                changes[key] = current[key];
            }
        });

        return changes;
    }

    hasChanges(): boolean {
        return Object.keys(this.getChanges()).length > 0;
    }
}
