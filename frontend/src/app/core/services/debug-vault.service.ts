import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface DebugVaultEntry {
    id: string;
    character_id?: string | null;
    kind: string;
    severity: string;
    summary: string;
    context?: Record<string, any> | null;
    output?: string;
    violations?: string[];
    runtime_meta?: Record<string, any> | null;
    reviewed: boolean;
    reviewed_at?: string | null;
    reviewed_note?: string | null;
    created_at: string;
}

export interface DebugVaultListResponse {
    entries: DebugVaultEntry[];
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
}

@Injectable({ providedIn: 'root' })
export class DebugVaultService {
    private readonly apiUrl = `${environment.apiBaseUrl}/debug_vault`;

    constructor(private http: HttpClient) {}

    list$(options: {
        kind?: string;
        reviewed?: boolean;
        limit?: number;
        offset?: number;
    } = {}): Observable<DebugVaultListResponse> {
        const params: Record<string, string> = {};
        if (options.kind) {
            params['kind'] = options.kind;
        }
        if (options.reviewed !== undefined) {
            params['reviewed'] = String(options.reviewed);
        }
        params['limit'] = String(options.limit ?? 50);
        params['offset'] = String(options.offset ?? 0);
        return this.http.get<DebugVaultListResponse>(`${this.apiUrl}/`, { params });
    }

    get$(entryId: string): Observable<DebugVaultEntry> {
        return this.http.get<DebugVaultEntry>(`${this.apiUrl}/${encodeURIComponent(entryId)}`);
    }

    markReviewed$(entryId: string, note?: string): Observable<{ id: string; reviewed: boolean }> {
        const body: Record<string, any> = {};
        if (note) {
            body['note'] = note;
        }
        return this.http.post<{ id: string; reviewed: boolean }>(
            `${this.apiUrl}/${encodeURIComponent(entryId)}/review`,
            body,
        );
    }
}
