import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';
import { Observable } from 'rxjs';
import { Message } from '../models/message.model';
import { map } from 'rxjs/operators';
import { mapVoiceModelToDto } from '../utils/voice-config-mapper';

export interface VoiceModeResponse {
    status: string;
    message: string;
    running: boolean;
}

export interface VoicePlaybackStatusResponse {
    status: string;
    speaking: boolean;
    stage: string;
    timestamp?: string;
}

export interface VoiceProvidersResponse {
    status: string;
    providers: {
        coqui?: {
            available?: boolean;
            disabled?: boolean;
            cooldown?: number;
            last_error?: string | null;
            meta?: {
                preload_enabled?: boolean;
                preload_state?: 'idle' | 'preloading' | 'loaded';
                engine_loaded?: boolean;
                keep_model_loaded?: boolean;
                device_requested?: string;
                effective_device?: string;
                last_init_error?: string | null;
                rvc?: {
                    enabled?: boolean;
                    model_selected?: boolean;
                    model_file?: string;
                    base_assets_ready?: boolean;
                    embedder_ready?: boolean;
                    available_f0_methods?: string[];
                    available_embedder_models?: string[];
                    dependency_status?: Record<string, boolean>;
                    local_models_count?: number;
                    last_error?: string | null;
                    fallback_active?: boolean;
                    preload_state?: 'disabled' | 'idle' | 'preloading' | 'loaded' | 'error' | 'on_demand' | string;
                    model_loaded?: boolean;
                    loaded_model_file?: string;
                    embedder_loaded?: boolean;
                    f0_method_ready?: boolean;
                };
            };
        };
        [key: string]: any;
    };
}

export interface ImportedVoiceFile {
    name: string;
    path: string;
    format: string;
}

export interface ImportVoiceResponse {
    status: string;
    original_file: ImportedVoiceFile;
    processed_file: ImportedVoiceFile;
    original_duration_seconds: number;
    processed_duration_seconds: number;
    recommended_range_seconds?: {
        min: number;
        max: number;
    } | null;
    truncated?: boolean;
    sample_rate: number;
    channels: number;
    original_summary?: {
        duration_seconds?: number;
        sample_rate?: number;
        channels?: number;
        codec?: string;
        size_bytes?: number;
        is_prepared_xtts?: boolean;
        health?: string;
        hint?: string;
    };
    processed_summary?: {
        duration_seconds?: number;
        sample_rate?: number;
        channels?: number;
        codec?: string;
        size_bytes?: number;
        is_prepared_xtts?: boolean;
        health?: string;
        hint?: string;
    };
}

@Injectable({
    providedIn: 'root'
})
export class VoiceService {
    apiUrl: string = `${environment.apiBaseUrl}/voice`;

    constructor(private http: HttpClient) { }

    stopPlay$(): Observable<any> {
        return this.http.post(`${this.apiUrl}/stop`, {});
    }

    playMessage(message_id: string): Observable<any> {
        return this.http.post<{ status: string; context: any }>(`${this.apiUrl}/play`, { message_id });
    }

    startRecord$(): Observable<any> {
        return this.http.post(`${this.apiUrl}/record/start`, {}).pipe(map((res) => {
            console.log({ res });
            return res;
        }));
    }

    stopRecord$(): Observable<{ data: Message }> {
        return this.http.post<{ data: Message }>(`${this.apiUrl}/record/stop`, {});
    }

    voiceModeStatus$(): Observable<VoiceModeResponse> {
        return this.http.get<VoiceModeResponse>(`${this.apiUrl}/mode/status`);
    }

    voiceModeStart$(): Observable<VoiceModeResponse> {
        return this.http.post<VoiceModeResponse>(`${this.apiUrl}/mode/start`, {});
    }

    voiceModeStop$(): Observable<VoiceModeResponse> {
        return this.http.post<VoiceModeResponse>(`${this.apiUrl}/mode/stop`, {});
    }

    playbackStatus$(): Observable<VoicePlaybackStatusResponse> {
        return this.http.get<VoicePlaybackStatusResponse>(`${this.apiUrl}/playback/status`);
    }

    providersStatus$(): Observable<VoiceProvidersResponse> {
        return this.http.get<VoiceProvidersResponse>(`${this.apiUrl}/providers`);
    }

    downloadXttsModel$(model: string): Observable<any> {
        return this.http.post(`${this.apiUrl}/xtts/download`, { model });
    }

    importVoice$(file: File): Observable<ImportVoiceResponse> {
        const encodedName = encodeURIComponent(file.name || 'voice_sample');
        return this.http.post<ImportVoiceResponse>(
            `${this.apiUrl}/import?filename=${encodedName}`,
            file,
        );
    }

    preview$(text: string): Observable<any>;
    preview$(text: string, voice: any): Observable<Blob>;
    preview$(text: string, voice?: any): Observable<any> {
        if (voice !== undefined) {
            return this.http.post(`${this.apiUrl}/preview`, {
                text,
                voice: mapVoiceModelToDto(voice),
            }, {
                responseType: 'blob',
            });
        }
        return this.http.post(`${this.apiUrl}/preview`, { text });
    }
}
