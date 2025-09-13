import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { ConfigService } from '../../../../../core/services/config.service';
import { ResourcesService } from '../../../../../core/services/resources.service';
import { ModalService } from '../../../../../shared/components/modal/modal.service';
import { MonitorSelectionModalComponent } from '../../monitor-selection-modal/monitor-selection-modal.component';

@Component({
    selector: 'app-vision-settings',
    templateUrl: './vision-settings.component.html',
    styleUrls: ['./vision-settings.component.less']
})
export class VisionSettingsComponent implements OnInit {
    visionForm: FormGroup;
    originalConfig: any = {};

    constructor(
        private fb: FormBuilder,
        private configService: ConfigService,
        private resourcesService: ResourcesService,
        private modalService: ModalService
    ) {
        this.visionForm = this.createForm();
    }

    ngOnInit(): void {
        this.loadConfig();
    }

    private createForm(): FormGroup {
        return this.fb.group({
            enabled: [false],
            monitorIndex: [0],
            fps: [5],
            bufferSec: [4],
            downscaleWidth: [1280],
            yoloEnabled: [false],
            ocrLang: ['rus+eng'],
            ocrMinConf: [70],
            ocrMaxLines: [5],
            region: [null]
        });
    }

    private loadConfig(): void {
        this.configService.getConfig$().subscribe(config => {
            if (config && config.vision) {
                this.originalConfig = { ...config.vision };
                this.visionForm.patchValue(config.vision);
            } else {
                this.originalConfig = { ...this.visionForm.value };
            }
        });
    }

    // ИСПРАВЛЕННЫЙ МЕТОД - Открытие модалки с выбором монитора
    openMonitorSelection(): void {
        this.resourcesService.getMonitorScreens$().subscribe(response => {
            if (response && response.monitors) {
                const modalRef = this.modalService.open(MonitorSelectionModalComponent, {
                    data: {
                        monitors: response.monitors,
                        selectedMonitor: this.visionForm.get('monitorIndex')?.value,
                        onSelect: (result: any) => {
                            // Этот callback будет вызван при выборе монитора в модалке
                            if (result && result.selectedMonitor !== undefined) {
                                console.log('Monitor selected in modal:', result.selectedMonitor);
                                this.visionForm.get('monitorIndex')?.setValue(result.selectedMonitor);
                            }
                        }
                    }
                });

                // Подписка на закрытие модалки
                modalRef.afterClosed$.subscribe((response) => {
                    // Этот callback вызывается когда модалка закрывается
                    const selectedMonitor = response?.selectedMonitor;
                    if (selectedMonitor !== undefined) {
                        console.log('Monitor selected on modal close:', selectedMonitor);
                        this.visionForm.get('monitorIndex')?.setValue(selectedMonitor);
                    }
                });
            }
        });
    }

    saveChanges(): void {
        const changes = this.getChanges();
        if (Object.keys(changes).length > 0) {
            const updateData = { vision: changes };
            this.configService.updateCongif$(updateData).subscribe({
                next: (response) => {
                    console.log('Vision settings updated:', response);
                    this.originalConfig = { ...this.visionForm.value };
                },
                error: (error) => {
                    console.error('Error updating vision settings:', error);
                }
            });
        }
    }

    private getChanges(): any {
        const current = this.visionForm.value;
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
