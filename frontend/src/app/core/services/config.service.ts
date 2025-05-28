import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { ProjectConfig } from '../models/project-config.model';
import { HttpClient } from '@angular/common/http';
import { ProjectConfigDto } from '../models/project-config.dto';
import { catchError, map } from 'rxjs/operators'
import { mapProjectConfigDtoToModel, mapPartialModelToDto } from '../utils/project-config.mapper';
import { environment } from '../../../environments/environment';
import { GenerationPreset } from '../models/generation-preset.model';


@Injectable({
    providedIn: 'root'
})
export class ConfigService {
    private apiUrl = environment.apiBaseUrl;

    constructor(private http: HttpClient) { }

    getConfig$(): Observable<ProjectConfig | null> {
        return this.http.get<ProjectConfigDto>(`${this.apiUrl}/config/`).pipe(
            map(mapProjectConfigDtoToModel),
            catchError((_err) => of(null))
        )
    }

    updateCongif$(body: ProjectConfig): Observable<any> {
        return this.http.patch(`${this.apiUrl}/config`, mapPartialModelToDto(body));
    }

    getGenerationPresets$(): Observable<GenerationPreset[]> {
        return this.http.get<{ status: string; presets: GenerationPreset[] }>(`${this.apiUrl}/presets/`).pipe(
            map(({ presets }) => presets),
            catchError((_err) => of([]))
        )
    }

    saveGenerationPreset$(preset: GenerationPreset): Observable<any> {
        return this.http.post(`${this.apiUrl}/presets/`, preset)
    }
}
