import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { shareReplay } from 'rxjs/operators';
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
    sampler?: string | null;
    scheduler?: string | null;
    comfyuiCheckpoint?: string | null;
    persistOutput?: boolean | null;
}

export interface SynthesisImageResponse {
    status: string;
    provider: string;
    mime_type: string;
    width: number;
    height: number;
    seed?: number | null;
    output_path?: string | null;
    image_base64: string;
    model_id?: string;
}

export interface SynthesisModelInfo {
    model_id: string;
    label: string;
    family: string;
    provider?: string;
    source: string;
    installed: boolean;
    path?: string | null;
    vae_path?: string | null;
    hf_repo_id?: string | null;
    default?: boolean;
    defaults?: Record<string, any> | null;
    capabilities?: Record<string, any> | null;
}

export interface SynthesisModelsResponse {
    status: string;
    models: SynthesisModelInfo[];
    default_model?: string | null;
    local_models_root?: string | null;
}

export interface SynthesisModelImportPathRequest {
    sourcePath: string;
    label?: string;
    modelId?: string;
    family?: string;
    vaePath?: string;
}

export interface ComfyUIStatusResponse {
    status: string;
    comfyui: {
        enabled: boolean;
        available: boolean;
        base_url: string;
        configured_checkpoint?: string;
        nodes_count?: number;
        system?: any;
        queue?: any;
        resources?: {
            checkpoints?: string[];
            loras?: string[];
            vaes?: string[];
            controlnets?: string[];
            embeddings?: string[];
            samplers?: string[];
            schedulers?: string[];
        };
        endpoints?: Array<{ path: string; method: string; purpose?: string }>;
        probed_endpoints?: Array<{ path: string; method: string; ok: boolean; status?: number; elapsed_ms?: number; error?: string }>;
    };
}

@Injectable({
    providedIn: 'root',
})
export class SynthesisService {
    private readonly apiUrl = `${environment.apiBaseUrl}/synthesis`;
    private modelsCache$?: Observable<SynthesisModelsResponse>;
    private comfyuiStatusCache$?: Observable<ComfyUIStatusResponse>;

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
            sampler: request.sampler,
            scheduler: request.scheduler,
            comfyui_checkpoint: request.comfyuiCheckpoint,
            persist_output: request.persistOutput,
        });
    }

    getModels$(refresh = false): Observable<SynthesisModelsResponse> {
        if (!refresh && this.modelsCache$) {
            return this.modelsCache$;
        }
        const suffix = refresh ? '?refresh=true' : '';
        this.modelsCache$ = this.http.get<SynthesisModelsResponse>(`${this.apiUrl}/models${suffix}`).pipe(shareReplay(1));
        return this.modelsCache$;
    }

    importCheckpoint$(file: File): Observable<any> {
        const encodedName = encodeURIComponent(file.name || 'checkpoint.safetensors');
        return this.http.post(
            `${this.apiUrl}/models/import?kind=checkpoint&filename=${encodedName}`,
            file,
        );
    }

    importCheckpointFromPath$(request: SynthesisModelImportPathRequest): Observable<any> {
        return this.http.post(`${this.apiUrl}/models/import-path`, {
            source_path: request.sourcePath,
            label: request.label || '',
            model_id: request.modelId || '',
            family: request.family || 'auto',
            vae_path: request.vaePath || '',
        });
    }

    getComfyUIStatus$(refresh = false): Observable<ComfyUIStatusResponse> {
        if (!refresh && this.comfyuiStatusCache$) {
            return this.comfyuiStatusCache$;
        }
        this.comfyuiStatusCache$ = this.http.get<ComfyUIStatusResponse>(`${this.apiUrl}/comfyui/status`).pipe(shareReplay(1));
        return this.comfyuiStatusCache$;
    }

    invalidateCache(): void {
        this.modelsCache$ = undefined;
        this.comfyuiStatusCache$ = undefined;
    }
}
