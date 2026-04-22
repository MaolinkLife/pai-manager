import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../../environments/environment';

@Injectable({
    providedIn: 'root'
})
export class ResourcesService {
    private apiUrl = environment.apiBaseUrl;

    constructor(private http: HttpClient) { }

    getAudioDevices$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/resources/devices`).pipe(
            catchError((error) => {
                console.error('Error getting audio devices:', error);
                return of({});
            })
        );
    }

    getMonitorScreens$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/resources/monitors/screens`).pipe(
            catchError((error) => {
                console.error('Error getting monitor screens:', error);
                return of({ monitors: [] });
            })
        );
    }

    getMonitorInfo$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/resources/monitors/info`).pipe(
            catchError((error) => {
                console.error('Error getting monitor info:', error);
                return of({ data: {} });
            })
        );
    }

    getEdgeVoices$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/resources/voices`).pipe(
            catchError((error) => {
                console.error('Error getting edge voices:', error);
                return of({ voices: [] });
            })
        );
    }

    getVoiceProviders$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/voice/providers`).pipe(
            catchError((error) => {
                console.error('Error getting voice providers status:', error);
                return of({ status: 'error', providers: {} });
            })
        );
    }

    getRvcStatus$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/voice/rvc/status`).pipe(
            catchError((error) => {
                console.error('Error getting RVC status:', error);
                return of({ status: 'error', rvc: null });
            })
        );
    }

    getLocalVoiceFiles$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/resources/local-voice-files?t=${Date.now()}`).pipe(
            catchError((error) => {
                console.error('Error getting local voice files:', error);
                return of({ status: 'success', files: [] });
            })
        );
    }

    getLocalVoiceFileUrl(path: string): string {
        return `${this.apiUrl}/resources/local-voice-file?path=${encodeURIComponent(path)}`;
    }

    getLocalXttsModels$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/resources/local-xtts-models?t=${Date.now()}`).pipe(
            catchError((error) => {
                console.error('Error getting local XTTS models:', error);
                return of({ status: 'success', models: [] });
            })
        );
    }

    getLocalRvcModels$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/resources/local-rvc-models?t=${Date.now()}`).pipe(
            catchError((error) => {
                console.error('Error getting local RVC models:', error);
                return of({ status: 'success', models: [] });
            })
        );
    }

    getVisionProviderStatus$(
        provider?: string | null,
        model?: string | null,
        probe = false,
    ): Observable<any> {
        const params = new URLSearchParams();
        if (provider) {
            params.set('provider', provider);
        }
        if (model) {
            params.set('model', model);
        }
        params.set('probe', String(!!probe));
        return this.http.get(`${this.apiUrl}/resources/vision/provider-status?${params.toString()}`).pipe(
            catchError((error) => {
                console.error('Error getting vision provider status:', error);
                return of({ status: 'error', provider: { ready: false, message: 'request failed' } });
            })
        );
    }
}
