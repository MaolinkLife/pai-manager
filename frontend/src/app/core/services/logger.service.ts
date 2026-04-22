import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { DebugLogsDto, LogsDto } from '../models/logs.model';

@Injectable({
    providedIn: 'root'
})
export class LoggerService {
    apiUrl: string = `${environment.apiBaseUrl}/log`;

    constructor(private http: HttpClient) { }

    getDebugLogPage$(limit: number, offset: number, sessionId?: string | null): Observable<DebugLogsDto> {
        const params: Record<string, string> = {
            limit: String(limit),
            offset: String(offset),
        };
        if (sessionId) {
            params['session_id'] = String(sessionId);
        }
        return this.http.get<DebugLogsDto>(this.apiUrl, {
            params,
        });
    }

    getDebugLog$(): Observable<LogsDto[]> {
        return this.http.get<DebugLogsDto>(this.apiUrl).pipe(
            map(({ logs, session_id }) => {
                return logs;
            })
        );
    }

    getAllDebugLogs$(sessionId?: string | null): Observable<DebugLogsDto> {
        const params: Record<string, string> = {};
        if (sessionId) {
            params['session_id'] = String(sessionId);
        }
        return this.http.get<DebugLogsDto>(this.apiUrl, { params });
    }
}
