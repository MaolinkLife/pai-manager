import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';
import { Observable } from 'rxjs';

@Injectable({
    providedIn: 'root'
})
export class VoiceService {
    apiUrl: string = `${environment.apiBaseUrl}/voice`;

    constructor(private http: HttpClient) { }

    stopPlay$(): Observable<any> {
        return this.http.post(`${this.apiUrl}/stop`, {});
    }

    playMessage(message_id: string): Observable<any> {
        return this.http.post<{ status: string; context: any }>(`${this.apiUrl}/play`, { message_id })
    }
}
