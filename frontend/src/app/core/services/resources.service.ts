import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, of } from 'rxjs';
import { catchError, shareReplay } from 'rxjs/operators';
import { environment } from '../../../environments/environment';

@Injectable({
    providedIn: 'root'
})
export class ResourcesService {
    private apiUrl = environment.apiBaseUrl;
    private readonly cache = new Map<string, Observable<any>>();

    constructor(private http: HttpClient) { }

    invalidateCache(key?: string): void {
        if (key) {
            this.cache.delete(key);
            return;
        }
        this.cache.clear();
    }

    private cached$(key: string, factory: () => Observable<any>, forceRefresh = false): Observable<any> {
        if (!forceRefresh && this.cache.has(key)) {
            return this.cache.get(key) as Observable<any>;
        }
        const request$ = factory().pipe(shareReplay(1));
        this.cache.set(key, request$);
        return request$;
    }

    getAudioDevices$(forceRefresh = false): Observable<any> {
        return this.cached$('audio-devices', () => this.http.get(`${this.apiUrl}/resources/devices`).pipe(
            catchError((error) => {
                console.error('Error getting audio devices:', error);
                return of({});
            })
        ), forceRefresh);
    }

    getMonitorScreens$(forceRefresh = false): Observable<any> {
        return this.cached$('monitor-screens', () => this.http.get(`${this.apiUrl}/resources/monitors/screens`).pipe(
            catchError((error) => {
                console.error('Error getting monitor screens:', error);
                return of({ monitors: [] });
            })
        ), forceRefresh);
    }

    getMonitorInfo$(forceRefresh = false): Observable<any> {
        return this.cached$('monitor-info', () => this.http.get(`${this.apiUrl}/resources/monitors/info`).pipe(
            catchError((error) => {
                console.error('Error getting monitor info:', error);
                return of({ data: {} });
            })
        ), forceRefresh);
    }

    getEdgeVoices$(forceRefresh = false): Observable<any> {
        return this.cached$('edge-voices', () => this.http.get(`${this.apiUrl}/resources/voices`).pipe(
            catchError((error) => {
                console.error('Error getting edge voices:', error);
                return of({ voices: [] });
            })
        ), forceRefresh);
    }

    getVoiceProviders$(forceRefresh = false): Observable<any> {
        return this.cached$('voice-providers', () => this.http.get(`${this.apiUrl}/voice/providers`).pipe(
            catchError((error) => {
                console.error('Error getting voice providers status:', error);
                return of({ status: 'error', providers: {} });
            })
        ), forceRefresh);
    }

    getRvcStatus$(forceRefresh = false): Observable<any> {
        return this.cached$('rvc-status', () => this.http.get(`${this.apiUrl}/voice/rvc/status`).pipe(
            catchError((error) => {
                console.error('Error getting RVC status:', error);
                return of({ status: 'error', rvc: null });
            })
        ), forceRefresh);
    }

    getLocalVoiceFiles$(forceRefresh = false): Observable<any> {
        return this.cached$('local-voice-files', () => this.http.get(`${this.apiUrl}/resources/local-voice-files?t=${Date.now()}`).pipe(
            catchError((error) => {
                console.error('Error getting local voice files:', error);
                return of({ status: 'success', files: [] });
            })
        ), forceRefresh);
    }

    getLocalVoiceFileUrl(path: string): string {
        return `${this.apiUrl}/resources/local-voice-file?path=${encodeURIComponent(path)}`;
    }

    getLocalXttsModels$(forceRefresh = false): Observable<any> {
        return this.cached$('local-xtts-models', () => this.http.get(`${this.apiUrl}/resources/local-xtts-models?t=${Date.now()}`).pipe(
            catchError((error) => {
                console.error('Error getting local XTTS models:', error);
                return of({ status: 'success', models: [] });
            })
        ), forceRefresh);
    }

    getLocalRvcModels$(forceRefresh = false): Observable<any> {
        return this.cached$('local-rvc-models', () => this.http.get(`${this.apiUrl}/resources/local-rvc-models?t=${Date.now()}`).pipe(
            catchError((error) => {
                console.error('Error getting local RVC models:', error);
                return of({ status: 'success', models: [] });
            })
        ), forceRefresh);
    }
}
