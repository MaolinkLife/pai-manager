import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface TunnelStatus {
    running: boolean;
    provider: string;
    command: string[];
    pid: number | null;
    public_url: string;
    started_at: string | null;
    stopped_at: string | null;
    last_error: string;
    last_logs: string[];
    config?: {
        enabled: boolean;
        provider: string;
        local_url: string;
        local_port: number;
        command_path: string;
        public_url: string;
    };
}

@Injectable({
    providedIn: 'root',
})
export class TunnelService {
    private readonly apiUrl = `${environment.apiBaseUrl}/tunnel`;

    constructor(private readonly http: HttpClient) {}

    getStatus$(): Observable<TunnelStatus> {
        return this.http.get<TunnelStatus>(`${this.apiUrl}/status`);
    }

    start$(overrides: Partial<TunnelStatus['config']> = {}): Observable<TunnelStatus> {
        return this.http.post<TunnelStatus>(`${this.apiUrl}/start`, overrides);
    }

    stop$(): Observable<TunnelStatus> {
        return this.http.post<TunnelStatus>(`${this.apiUrl}/stop`, {});
    }
}
