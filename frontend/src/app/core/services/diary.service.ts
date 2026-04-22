import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface DiaryEntryDto {
    id: string;
    character_id: string;
    day: string;
    mood: string;
    summary: string;
    tags: string[];
    stats: Record<string, any>;
    payload: Record<string, any>;
    created_at: string;
    updated_at: string;
}

export interface DiaryListResponse {
    status: string;
    entries: DiaryEntryDto[];
    total: number;
    days: number;
}

export interface DiaryGenerateResponse {
    status: string;
    generated: boolean;
    entry: DiaryEntryDto;
}

@Injectable({ providedIn: 'root' })
export class DiaryService {
    private readonly apiUrl = `${environment.apiBaseUrl}/memory`;

    constructor(private http: HttpClient) {}

    getEntries$(days = 30): Observable<DiaryListResponse> {
        const params = new HttpParams().set('days', String(days));
        return this.http.get<DiaryListResponse>(`${this.apiUrl}/diary`, { params });
    }

    generateEntry$(day?: string, force = false): Observable<DiaryGenerateResponse> {
        let params = new HttpParams().set('force', String(!!force));
        if (day && day.trim()) {
            params = params.set('day', day.trim());
        }
        return this.http.post<DiaryGenerateResponse>(`${this.apiUrl}/diary/generate`, null, {
            params,
        });
    }
}
