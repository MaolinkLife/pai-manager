import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import {
    MemoryEmulateResponse,
    MemoryHistoryResponse,
    MemoryListResponse,
    MemoryRefreshResponse,
    MemorySearchResponse,
} from '../models/memory.model';

@Injectable({
    providedIn: 'root',
})
export class MemoryService {
    private apiUrl = `${environment.apiBaseUrl}/memory`;

    constructor(private http: HttpClient) {}

    listShortTerm$(days = 30): Observable<MemoryListResponse> {
        const params = new HttpParams().set('days', String(days));
        return this.http
            .get<MemoryListResponse>(`${this.apiUrl}/short-term`, { params })
            .pipe(catchError(() => of({ records: [], total: 0, days })));
    }

    refresh$(days = 30): Observable<MemoryRefreshResponse> {
        const params = new HttpParams().set('days', String(days));
        return this.http
            .post<MemoryRefreshResponse>(`${this.apiUrl}/refresh`, null, { params })
            .pipe(catchError(() => of({ status: 'error', records: 0, days })));
    }

    search$(
        query: string,
        messageId: string,
        days = 30,
        limit = 50
    ): Observable<MemorySearchResponse> {
        let params = new HttpParams()
            .set('days', String(days))
            .set('limit', String(limit));

        if (query.trim()) {
            params = params.set('q', query.trim());
        }
        if (messageId.trim()) {
            params = params.set('message_id', messageId.trim());
        }

        return this.http
            .get<MemorySearchResponse>(`${this.apiUrl}/search`, { params })
            .pipe(
                catchError(() =>
                    of({
                        records: [],
                        total: 0,
                        query: query || null,
                        message_id: messageId || null,
                        days,
                        generated_at: null,
                    })
                )
            );
    }

    emulateSearch$(params: {
        q: string;
        messageId?: string;
        recentPairs?: number;
        windowPairs?: number;
        lookbackDays?: number;
        topK?: number;
    }): Observable<MemoryEmulateResponse> {
        let httpParams = new HttpParams()
            .set('q', params.q || '')
            .set('recent_pairs', String(params.recentPairs ?? 32))
            .set('window_pairs', String(params.windowPairs ?? 32))
            .set('lookback_days', String(params.lookbackDays ?? 7))
            .set('top_k', String(params.topK ?? 8));

        if ((params.messageId || '').trim()) {
            httpParams = httpParams.set('message_id', (params.messageId || '').trim());
        }

        return this.http
            .get<MemoryEmulateResponse>(`${this.apiUrl}/emulate-search`, {
                params: httpParams,
            })
            .pipe(
                catchError(() =>
                    of({
                        status: 'error',
                        query: params.q || '',
                        message_id: params.messageId || null,
                        character: { id: '', name: '' },
                        settings: {
                            recent_pairs: params.recentPairs ?? 32,
                            window_pairs: params.windowPairs ?? 32,
                            lookback_days: params.lookbackDays ?? 7,
                            top_k: params.topK ?? 8,
                            profiles: [],
                        },
                        trace: [],
                        hits: [],
                    })
                )
            );
    }

    listHistory$(limit = 32, offset = 0): Observable<MemoryHistoryResponse> {
        const params = new HttpParams()
            .set('limit', String(limit))
            .set('offset', String(offset));

        return this.http
            .get<MemoryHistoryResponse>(`${this.apiUrl}/history`, { params })
            .pipe(
                catchError(() =>
                    of({
                        status: 'error',
                        records: [],
                        limit,
                        offset,
                        has_more: false,
                    })
                )
            );
    }
}
