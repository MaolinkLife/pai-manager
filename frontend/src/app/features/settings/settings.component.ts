import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { ConfigService } from '../../core/services/config.service';
import { ProjectConfig } from '../../core/models/project-config.model';
import { ApiService } from '../../core/services/api.service';

@Component({
    selector: 'app-settings',
    templateUrl: './settings.component.html',
    styleUrls: ['./settings.component.less']
})
export class SettingsComponent implements OnInit {

    @ViewChild('tokenSlider') tokenSliderRef!: ElementRef<HTMLInputElement>;
    @ViewChild('tokenInput') tokenInputRef!: ElementRef<HTMLInputElement>;

    settingsForm: FormGroup;

    originalConfig!: ProjectConfig;

    constructor(
        private fb: FormBuilder,
        private configService: ConfigService,
        private apiService: ApiService,
    ) {
        this.settingsForm = this.fb.group({
            charName: [''],
            userName: [''],
            voice: this.fb.group({
                outputId: [0],
                windowsOutputId: [0],
                language: [''],
                useRvc: [false],
                voiceLanguage: ['']
            }),
            modules: this.fb.group({
                vtube_studio: [false],
                whisper: [false],
                minecraft: [false],
                gaming: [false],
                alarm: [false],
                discord: [false],
                rag: [false],
                visual: [false]
            }),
            api: this.fb.group({
                type: [''],
                streaming: [false],
                model: [''],
                visualModel: [''],
                tokenLimit: [0],
                messagePairLimit: [0]
            })
        });
    }

    ngOnInit(): void {
        this.configService.getConfig$().subscribe((data: ProjectConfig | null) => {
            if (data) {
                this.originalConfig = JSON.parse(JSON.stringify(data)); // глубокая копия
                this.settingsForm.patchValue(data);
            }
        });

        const tokenLimitControl = this.settingsForm.get('api.tokenLimit');

        // Обновляем range, если изменилось число
        tokenLimitControl?.valueChanges.subscribe(value => {
            if (!value) {
                return;
            }


            if (
                this.tokenSliderRef &&
                this.tokenSliderRef.nativeElement &&
                this.tokenSliderRef.nativeElement.value !== value.toString()
            ) {
                this.tokenSliderRef.nativeElement.value = value.toString();
            }

            if (
                this.tokenInputRef &&
                this.tokenInputRef.nativeElement &&
                this.tokenInputRef.nativeElement.value !== value.toString()
            ) {
                this.tokenInputRef.nativeElement.value = value.toString();
            }
        });
    }

    getModifiedConfig(): any {
        const current = this.settingsForm.value;

        const getDiff = (orig: any, curr: any): any => {
            let result: any = {};
            for (const key in curr) {
                if (typeof curr[key] === 'object' && curr[key] !== null && !Array.isArray(curr[key])) {
                    const nested = getDiff(orig[key] || {}, curr[key]);
                    if (Object.keys(nested).length > 0) {
                        result[key] = nested;
                    }
                } else if (curr[key] !== orig[key]) {
                    result[key] = curr[key];
                }
            }
            return result;
        };

        return getDiff(this.originalConfig, current);
    }

    clickUpdateConfig() {
        const changes = this.getModifiedConfig();

        if (Object.keys(changes).length === 0) {
            console.log("Нет изменений");
            return;
        }

        this.configService.updateCongif$(changes).subscribe(result => {
            console.log({ result });
            this.originalConfig = JSON.parse(JSON.stringify(this.settingsForm.value)); // обновляем базу
        });
    }

    hasChanges(): boolean {
        const current = this.settingsForm.getRawValue();
        return JSON.stringify(current) !== JSON.stringify(this.originalConfig);
    }

}
