import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';
import { Observable, of } from 'rxjs';
import { catchError, map } from 'rxjs/operators';

@Injectable({
    providedIn: 'root'
})
export class ApiService {
    private apiUrl = environment.apiBaseUrl;

    constructor(private http: HttpClient) { }

    getOllamaModels$(): Observable<string[]> {
        return this.http.get<{ status: string; models: string[] }>(`${this.apiUrl}/ollama/models`).pipe(
            map(({ models }) => models),
            catchError((_err) => of([]))
        );
    }

    sendMessage$(request: any): Observable<any> {
        return this.http.post<{ response: string }>(`${this.apiUrl}/ollama/chat`, request)
    }
}
