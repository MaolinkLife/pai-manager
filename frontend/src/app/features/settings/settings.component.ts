import { Component, OnInit } from '@angular/core';
import { ConfigService } from '../../core/services/config.service';
import { ProjectConfig } from '../../core/models/project-config.model';
import { ApiService } from '../../core/services/api.service';

@Component({
    selector: 'app-settings',
    templateUrl: './settings.component.html',
    styleUrls: ['./settings.component.less']
})
export class SettingsComponent implements OnInit {

    constructor(
        private configSerice: ConfigService,
        private apiService: ApiService,
    ) { }

    ngOnInit(): void {
        this.configSerice.getConfig$().subscribe((data: ProjectConfig | null) => {
            console.log({
                data
            });

        })

        this.apiService.getOllamaModels$().subscribe((models: string[]) => {
            if (!models.length) {
                return;
            }

            console.log({
                models
            });

        })
    }

    clickUpdateConfig() {
        this.configSerice.updateCongif$({
            char_name: 'Lim',
            user_name: 'Mao',
            modules: {
                rag: true,
            },
            custom_field: 'custom'
        }).subscribe((result) => {
            console.log({
                result
            });

        })
    }

}
