import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

@Injectable({
    providedIn: 'root'
})
export class LorebookService {
    apiUrl: string = `${environment.apiBaseUrl}/lorebook`;

    constructor(private http: HttpClient) { }

    getLorebook$(): Observable<any> {
        return this.http.get(this.apiUrl);
    }
}
