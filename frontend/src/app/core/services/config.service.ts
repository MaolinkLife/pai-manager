import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { ProjectConfig } from '../models/project-config.model';
import { HttpClient } from '@angular/common/http';
import { ProjectConfigDto } from '../models/project-config.dto';
import { catchError, map, tap } from 'rxjs/operators'
import { mapProjectConfigDtoToModel, mapPartialModelToDto } from '../utils/project-config.mapper';
import { environment } from '../../../environments/environment';
import { GenerationPreset } from '../models/generation-preset.model';

export interface SystemCharacter {
    id?: string;
    name: string;
    prompt: string;
    has_prompt?: boolean;
    source?: string;
    updated_at?: string | null;
}

export interface SystemPayload {
    active_character_id?: string | null;
    char_name: string;
    prompt: string;
    characters?: SystemCharacter[];
}

@Injectable({
    providedIn: 'root'
})
export class ConfigService {
    private apiUrl = environment.apiBaseUrl;

    constructor(private http: HttpClient) { }

    getConfig$(): Observable<ProjectConfig | null> {
        return this.http.get<ProjectConfigDto>(`${this.apiUrl}/config/`).pipe(
            tap((config: any) => {
                console.log('[Config Service] Load Config From Server:', { config });
            }),
            map(mapProjectConfigDtoToModel),
            catchError((_err) => of(null))
        )
    }

    updateConfig$(body: any): Observable<any> {
        // Если передается частичный конфиг - используем PATCH
        if (
            body.voice ||
            body.modules ||
            body.connector ||
            body.api ||
            body.vision ||
            body.audio ||
            body.rag ||
            body.analyzer ||
            body.moral ||
            body.system ||
            body.memory ||
            body.generateSettings
        ) {
            return this.http.patch(`${this.apiUrl}/config/`, mapPartialModelToDto(body));
        }
        // Иначе - используем POST для полной замены
        return this.http.post(`${this.apiUrl}/config/`, mapPartialModelToDto(body));
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

    // Новый метод для получения system
    getSystem$(): Observable<{ system: SystemPayload } | null> {
        return this.http.get<{ system: SystemPayload }>(`${this.apiUrl}/config/system`).pipe(
            catchError((_err) => of(null))
        );
    }


    // Новый метод для обновления system
    updateSystem$(prompt?: string, charName?: string, activeCharacterId?: string): Observable<any> {
        const body: any = {};
        if (prompt !== undefined) {
            body.prompt = prompt;
        }
        if (charName !== undefined) {
            body.char_name = charName;
        }
        if (activeCharacterId !== undefined) {
            body.active_character_id = activeCharacterId;
        }
        return this.http.post(`${this.apiUrl}/config/system`, body);
    }

    getSystemCharacters$(): Observable<{ active_character_id?: string | null; active_char_name: string; characters: SystemCharacter[] } | null> {
        return this.http.get<{ active_character_id?: string | null; active_char_name: string; characters: SystemCharacter[] }>(`${this.apiUrl}/config/system/characters`).pipe(
            catchError((_err) => of(null))
        );
    }

    importSystemCharacterYaml$(fileName: string, content: string, setActive = true): Observable<any> {
        return this.http.post(`${this.apiUrl}/config/system/characters/import`, {
            file_name: fileName,
            content,
            set_active: setActive,
        });
    }

    // Новый метод для получения конкретного значения из конфига (если нужно)
    getConfigValue$(path: string): Observable<any> {
        return this.getConfig$().pipe(
            map(config => {
                if (!config) return null;
                return this.getNestedValue(config, path);
            })
        );
    }

    private getNestedValue(obj: any, path: string): any {
        return path.split('.').reduce((current, key) => current?.[key], obj);
    }
}
