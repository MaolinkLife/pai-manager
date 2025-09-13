import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { ResourcesService } from '../../../../../core/services/resources.service';
import { Observable, forkJoin } from 'rxjs';
import { map, startWith } from 'rxjs/operators';

interface AudioDevice {
    id: number;
    name: string;
}

interface AudioDevicesData {
    audioOutputs: AudioDevice[];
    windowsOutputs: AudioDevice[];
}

@Component({
    selector: 'app-voice-settings',
    templateUrl: './voice-settings.component.html',
    styleUrls: ['./voice-settings.component.less']
})
export class VoiceSettingsComponent implements OnInit {
    voiceForm: FormGroup;
    originalConfig: any = {};

    // Observable для устройств
    devices$: Observable<AudioDevicesData> = new Observable<AudioDevicesData>();

    constructor(
        private fb: FormBuilder,
        private configService: ConfigService,
        private resourcesService: ResourcesService
    ) {
        this.voiceForm = this.createForm();
    }

    ngOnInit(): void {
        this.loadConfig();
        this.loadDevices();
    }

    private createForm(): FormGroup {
        return this.fb.group({
            enabled: [false],
            outputId: [0],
            windowsOutputId: [0],
            language: ['ru-RU'],
            useRvc: [false],
            voiceLanguage: ['ru-RU-SvetlanaNeural'],
            useWindowsOutput: [false],
            streamingTts: [false]
        });
    }

    private loadConfig(): void {
        this.configService.getConfig$().subscribe(config => {
            if (config && config.voice) {
                this.originalConfig = { ...config.voice };
                this.voiceForm.patchValue(config.voice);
                console.log('Voice config loaded:', config.voice);
            }
        });
    }

    private loadDevices(): void {
        this.devices$ = forkJoin({
            config: this.configService.getConfig$(),
            devices: this.resourcesService.getAudioDevices$()
        }).pipe(
            map(({ config, devices }) => {
                // Подготавливаем массивы устройств с Default Device
                const audioOutputs: AudioDevice[] = [
                    { id: 0, name: 'Default Device' },
                    ...(devices.all_devices || []).map(([id, name]: [number, string]) => ({ id, name }))
                ];

                const windowsOutputs: AudioDevice[] = [
                    { id: 0, name: 'Default Device' },
                    ...(devices.get_windows_output || []).map(([id, name]: [number, string]) => ({ id, name }))
                ];

                console.log('Audio devices loaded:', { audioOutputs, windowsOutputs });
                return { audioOutputs, windowsOutputs };
            }),
            startWith({
                audioOutputs: [{ id: 0, name: 'Loading...' }],
                windowsOutputs: [{ id: 0, name: 'Loading...' }]
            })
        );
    }

    saveChanges(): void {
        const changes = this.getChanges();
        if (Object.keys(changes).length > 0) {
            const updateData = { voice: changes };
            this.configService.updateCongif$(updateData).subscribe({
                next: (response) => {
                    console.log('Voice settings updated:', response);
                    this.originalConfig = { ...this.voiceForm.value };
                },
                error: (error) => {
                    console.error('Error updating voice settings:', error);
                }
            });
        }
    }

    private getChanges(): any {
        const current = this.voiceForm.value;
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
