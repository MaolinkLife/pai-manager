import { Injectable, signal } from '@angular/core';
import { Observable, of } from 'rxjs';
import { ProjectConfig } from '../models/project-config.model';
import { HttpClient } from '@angular/common/http';
import { ProjectConfigDto } from '../models/project-config.dto';
import { catchError, finalize, map, shareReplay, tap } from 'rxjs/operators'
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

/** What deleting a character would archive and remove (GET .../deletion-preview). */
export interface CharacterDeletionPreview {
    status?: string;
    character: { id: string; name: string };
    counts: Record<string, number>;
    has_data: boolean;
    files: number;
    files_bytes: number;
    library_files: number;
    blocked: { code: string; message: string } | null;
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
    private readonly configState = signal<ProjectConfig | null>(null);
    private configLoad$?: Observable<ProjectConfig | null>;
    private defaultsLoad$?: Observable<Record<string, any> | null>;

    constructor(private http: HttpClient) { }

    readonly config = this.configState.asReadonly();

    getConfig$(forceRefresh = false): Observable<ProjectConfig | null> {
        const cached = this.configState();
        if (cached && !forceRefresh) {
            return of(cached);
        }
        if (this.configLoad$ && !forceRefresh) {
            return this.configLoad$;
        }
        this.configLoad$ = this.http.get<ProjectConfigDto>(`${this.apiUrl}/config/`).pipe(
            tap((config: any) => {
                console.log('[Config Service] Load Config From Server:', { config });
            }),
            map(mapProjectConfigDtoToModel),
            tap((config) => this.configState.set(config)),
            catchError((_err) => of(null)),
            finalize(() => {
                this.configLoad$ = undefined;
            }),
            shareReplay(1)
        );
        return this.configLoad$;
    }

    refreshConfig$(): Observable<ProjectConfig | null> {
        return this.getConfig$(true);
    }

    invalidateConfig(): void {
        this.configState.set(null);
        this.configLoad$ = undefined;
    }

    /**
     * Partial config update. PATCH merges recursively on the backend
     * (`update_config_bulk` -> `_recursive_update`), so keys absent from the body
     * are left untouched — every settings form is safe to call this.
     *
     * This used to pick PATCH or POST by matching the body against a hardcoded list
     * of top-level section names, and POST replaces the whole config. Any section
     * whose key was missing from that list would therefore overwrite everything else
     * on save. The list was complete at the time, so the bug never fired — it would
     * have fired on the next section added. Use `replaceConfig$` when a full
     * replacement is genuinely intended.
     */
    updateConfig$(body: any): Observable<any> {
        return this.http.patch(`${this.apiUrl}/config/`, mapPartialModelToDto(body)).pipe(
            tap(() => this.invalidateConfig())
        );
    }

    /**
     * Full config replacement — everything not present in `body` is dropped.
     * Only for deliberate whole-config operations such as import or reset to defaults.
     */
    replaceConfig$(body: any): Observable<any> {
        return this.http.post(`${this.apiUrl}/config/`, mapPartialModelToDto(body)).pipe(
            tap(() => this.invalidateConfig())
        );
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

    createSystemCharacter$(name: string, setActive = true): Observable<any> {
        return this.http.post(`${this.apiUrl}/config/system/characters`, {
            name,
            set_active: setActive,
        });
    }

    getCharacterDeletionPreview$(characterId: string): Observable<CharacterDeletionPreview> {
        return this.http.get<CharacterDeletionPreview>(
            `${this.apiUrl}/config/system/characters/${encodeURIComponent(characterId)}/deletion-preview`
        );
    }

    deleteSystemCharacter$(characterId: string): Observable<any> {
        return this.http.delete(`${this.apiUrl}/config/system/characters/${encodeURIComponent(characterId)}`);
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

    /**
     * The built-in value at a snake_case config path, e.g. `validator.system_prompt`.
     * "Reset to default" on a settings field takes its value from here.
     */
    getDefaultValue$(path: string): Observable<any> {
        if (!this.defaultsLoad$) {
            this.defaultsLoad$ = this.http.get<Record<string, any>>(`${this.apiUrl}/config/defaults`).pipe(
                catchError((_err) => {
                    this.defaultsLoad$ = undefined;
                    return of(null);
                }),
                shareReplay(1),
            );
        }
        return this.defaultsLoad$.pipe(
            map((defaults) => (defaults ? this.getNestedValue(defaults, path) : null)),
        );
    }

    private getNestedValue(obj: any, path: string): any {
        return path.split('.').reduce((current, key) => current?.[key], obj);
    }
}
