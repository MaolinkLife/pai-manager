import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

@Injectable({
    providedIn: 'root'
})
export class ResourcesService {
    apiUrl: string = `${environment.apiBaseUrl}/resources`;

    constructor(private http: HttpClient) { }

    getAudioDevices$(): Observable<any> {
        return this.http.get(`${this.apiUrl}/devices`);
    }
}
