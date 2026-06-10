import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface ReminderDto {
    id: string;
    character_id: string;
    user_uuid: string | null;
    text: string;
    due_at: string | null;
    recurrence: string;
    channel: string;
    status: 'pending' | 'fired' | 'cancelled' | 'failed';
    source: string;
    source_message_id: string | null;
    fired_at: string | null;
    meta: Record<string, any>;
    created_at: string | null;
}

export interface ReminderListResponse {
    status: string;
    items: ReminderDto[];
    total: number;
}

@Injectable({
    providedIn: 'root',
})
export class ReminderService {
    private readonly apiUrl = `${environment.apiBaseUrl}/reminders`;

    constructor(private http: HttpClient) {}

    list$(options: { status?: string; limit?: number; offset?: number } = {}): Observable<ReminderListResponse> {
        let params = new HttpParams();
        if (options.status) {
            params = params.set('status', options.status);
        }
        params = params.set('limit', String(options.limit ?? 100));
        params = params.set('offset', String(options.offset ?? 0));
        return this.http.get<ReminderListResponse>(`${this.apiUrl}/`, { params });
    }

    create$(payload: { text: string; due_at: string; channel?: string }): Observable<{ status: string; reminder: ReminderDto }> {
        return this.http.post<{ status: string; reminder: ReminderDto }>(`${this.apiUrl}/`, payload);
    }

    update$(id: string, payload: { text?: string; due_at?: string }): Observable<{ status: string; reminder: ReminderDto }> {
        return this.http.patch<{ status: string; reminder: ReminderDto }>(`${this.apiUrl}/${id}`, payload);
    }

    cancel$(id: string): Observable<{ status: string; reminder: ReminderDto }> {
        return this.http.post<{ status: string; reminder: ReminderDto }>(`${this.apiUrl}/${id}/cancel`, {});
    }
}
