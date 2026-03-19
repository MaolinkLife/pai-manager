import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface SynthesisImageRequest {
    prompt: string;
    provider?: string;
    model?: string;
    aspectRatio?: string;
    width?: number;
    height?: number;
    negativePrompt?: string;
    numInferenceSteps?: number;
    guidanceScale?: number;
    seed?: number | null;
}

export interface SynthesisImageResponse {
    status: string;
    provider: string;
    mime_type: string;
    width: number;
    height: number;
    seed?: number | null;
    image_base64: string;
    model_id?: string;
}

export interface SynthesisModelInfo {
    model_id: string;
    label: string;
    family: string;
    source: string;
    installed: boolean;
    path?: string | null;
    hf_repo_id?: string | null;
    default?: boolean;
    defaults?: Record<string, any> | null;
}

export interface SynthesisModelsResponse {
    status: string;
    models: SynthesisModelInfo[];
    default_model?: string | null;
}

@Injectable({
    providedIn: 'root',
})
export class SynthesisService {
    private readonly apiUrl = `${environment.apiBaseUrl}/synthesis`;

    constructor(private http: HttpClient) {}

    generateImage$(request: SynthesisImageRequest): Observable<SynthesisImageResponse> {
        return this.http.post<SynthesisImageResponse>(`${this.apiUrl}/image/generate`, {
            prompt: request.prompt,
            provider: request.provider,
            model: request.model,
            aspect_ratio: request.aspectRatio,
            width: request.width,
            height: request.height,
            negative_prompt: request.negativePrompt,
            num_inference_steps: request.numInferenceSteps,
            guidance_scale: request.guidanceScale,
            seed: request.seed,
        });
    }

    getModels$(refresh = false): Observable<SynthesisModelsResponse> {
        const suffix = refresh ? '?refresh=true' : '';
        return this.http.get<SynthesisModelsResponse>(`${this.apiUrl}/models${suffix}`);
    }
}
