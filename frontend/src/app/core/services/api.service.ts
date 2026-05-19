import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';
import { Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';
import { Message } from '../models/message.model';

export interface LocalModelResourceItem {
    id: string;
    name: string;
    path: string;
    absolute_path?: string;
    source: string;
    size_bytes?: number;
    type?: string;
}

export interface LocalModelResourcesResponse {
    status: string;
    groups: Record<string, LocalModelResourceItem[]>;
    counts: Record<string, number>;
    total_count: number;
}

export interface ModelCapabilitiesResponse {
    status: string;
    model: string;
    capabilities: {
        tool: boolean;
        vision: boolean;
        thinking: boolean;
    };
    details?: Record<string, any>;
}

export interface OllamaRuntimeModel {
    name: string;
    model: string;
    loaded: boolean;
    size?: number;
    digest?: string;
    modified_at?: string;
    expires_at?: string | null;
    size_vram?: number | null;
    processor?: string | null;
    details?: Record<string, any>;
    runtime?: Record<string, any> | null;
}

export interface OllamaRuntimeModelsResponse {
    status: string;
    models: OllamaRuntimeModel[];
    message?: string;
}

export interface OllamaUnloadResponse {
    status: string;
    model?: string;
    message?: string;
}

export interface SandboxGenerateRequest {
    mode: 'text';
    provider: string;
    model?: string;
    system_prompt?: string;
    user_prompt: string;
    temperature?: number;
    top_p?: number;
    top_k?: number;
    max_tokens?: number;
    options?: Record<string, any>;
}

export interface SandboxGenerateResponse {
    status: string;
    provider: string;
    model?: string;
    content: string;
    reasoning?: string;
    metadata?: Record<string, any>;
    tool_calls?: any[];
    elapsed_ms?: number;
}

export interface SandboxCase {
    id: string;
    title: string;
    prompt: string;
    requires?: string[];
}

export interface SandboxPipelineRequest {
    mode: 'direct' | 'full';
    provider: string;
    model?: string;
    system_prompt?: string;
    user_prompt: string;
    temperature?: number;
    top_p?: number;
    top_k?: number;
    max_tokens?: number;
    media?: any[];
    case_id?: string;
    options?: Record<string, any>;
}

export interface SandboxImagePipelineRequest extends Omit<SandboxPipelineRequest, 'mode'> {
    mode: 'image';
    image_provider: string;
    image_model?: string;
    image_negative_prompt?: string;
    width?: number;
    height?: number;
    num_inference_steps?: number;
    guidance_scale?: number;
    seed?: number | null;
    sampler?: string | null;
    scheduler?: string | null;
    comfyui_checkpoint?: string | null;
    use_unified_router?: boolean | null;
    use_prompt_builder?: boolean | null;
    image_prompt_policy?: string;
    image_style_prompt?: string;
    persist_output?: boolean | null;
}

export interface SandboxVisionRequest extends Omit<SandboxPipelineRequest, 'mode'> {
    mode: 'vision';
}

export interface SandboxPipelineResponse extends SandboxGenerateResponse {
    mode: 'direct' | 'full' | 'image' | 'vision';
    media?: any[];
    mime_type?: string;
    image_base64?: string;
    image_prompt?: string;
    negative_prompt?: string;
    image_parameters?: Record<string, any>;
    vision_description?: string;
    traces?: Array<{
        stage: string;
        state: string;
        elapsed_ms?: number;
        details?: Record<string, any>;
        timestamp?: string;
    }>;
    usage?: Record<string, any>;
}

@Injectable({
    providedIn: 'root'
})
export class ApiService {
    private apiUrl = `${environment.apiBaseUrl}/ollama`;
    private resourcesApiUrl = `${environment.apiBaseUrl}/resources`;
    private sandboxApiUrl = `${environment.apiBaseUrl}/sandbox`;

    constructor(private http: HttpClient) { }

    getOllamaModels$(): Observable<string[]> {
        return this.http.get<{ status: string; models: string[] }>(`${this.apiUrl}/models`).pipe(
            map(({ models }) => models),
            catchError((_err) => of([]))
        );
    }

    checkOllamaCapabilities$(model: string): Observable<ModelCapabilitiesResponse | null> {
        return this.http
            .post<ModelCapabilitiesResponse>(`${this.apiUrl}/capabilities/check`, {
                model,
                checks: {
                    tool: true,
                    vision: true,
                    thinking: true,
                },
            })
            .pipe(catchError((_err) => of(null)));
    }

    getOllamaRuntimeModels$(): Observable<OllamaRuntimeModelsResponse | null> {
        return this.http
            .get<OllamaRuntimeModelsResponse>(`${this.apiUrl}/runtime/models`)
            .pipe(catchError((_err) => of(null)));
    }

    unloadOllamaModel$(model: string): Observable<OllamaUnloadResponse | null> {
        return this.http
            .post<OllamaUnloadResponse>(`${this.apiUrl}/runtime/unload`, { model })
            .pipe(catchError((_err) => of(null)));
    }

    getLocalModels$(limitPerGroup: number = 300): Observable<LocalModelResourcesResponse | null> {
        return this.http
            .get<LocalModelResourcesResponse>(`${this.resourcesApiUrl}/local-models?limit_per_group=${limitPerGroup}`)
            .pipe(catchError((_err) => of(null)));
    }

    sendMessage$(request: any): Observable<any> {
        return this.http.post<{ response: string }>(`${this.apiUrl}/chat`, request)
    }

    getChatHistory$(limit: number = 32) {
        return this.http.get<{ status: string; history: Message[] }>(`${this.apiUrl}/history?limit=${limit}`)
    }

    deleteMessage$(messageId: string, chain: boolean): Observable<any> {
        return this.http.delete<{ status: string; deleted?: number }>(`${this.apiUrl}/history/message?message_id=${messageId}&chain=${chain}`)
    }

    rerollMessage$(messageId: string) {
        return this.http.post<any>(`${this.apiUrl}/history/reroll`, { message_id: messageId });
    }

    sandboxGenerate$(request: SandboxGenerateRequest): Observable<SandboxGenerateResponse> {
        return this.http.post<SandboxGenerateResponse>(`${this.sandboxApiUrl}/generate`, request);
    }

    getSandboxCases$(): Observable<SandboxCase[]> {
        return this.http
            .get<{ status: string; cases: SandboxCase[] }>(`${this.sandboxApiUrl}/cases`)
            .pipe(
                map(({ cases }) => cases || []),
                catchError((_err) => of([]))
            );
    }

    sandboxPipelineTest$(request: SandboxPipelineRequest): Observable<SandboxPipelineResponse> {
        return this.http.post<SandboxPipelineResponse>(`${this.sandboxApiUrl}/pipeline-test`, request);
    }

    sandboxImagePipeline$(request: SandboxImagePipelineRequest): Observable<SandboxPipelineResponse> {
        return this.http.post<SandboxPipelineResponse>(`${this.sandboxApiUrl}/image-pipeline`, request);
    }

    sandboxVision$(request: SandboxVisionRequest): Observable<SandboxPipelineResponse> {
        return this.http.post<SandboxPipelineResponse>(`${this.sandboxApiUrl}/vision`, request);
    }

    sandboxTranscribe$(file: File): Observable<{ status: string; transcript: string; elapsed_ms?: number; filename?: string }> {
        const formData = new FormData();
        formData.append('file', file);
        return this.http.post<{ status: string; transcript: string; elapsed_ms?: number; filename?: string }>(
            `${this.sandboxApiUrl}/transcribe`,
            formData
        );
    }
}
