import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { LibraryContentResponse, LibraryItem, LibraryListResponse } from '../models/library.model';

@Injectable({
    providedIn: 'root',
})
export class LibraryService {
    private readonly apiUrl = `${environment.apiBaseUrl}/media`;

    constructor(private http: HttpClient) {}

    list$(options: { limit?: number; offset?: number; q?: string; category?: string } = {}): Observable<LibraryListResponse> {
        let params = new HttpParams()
            .set('limit', String(options.limit ?? 200))
            .set('offset', String(options.offset ?? 0));
        if (options.q) {
            params = params.set('q', options.q);
        }
        if (options.category && options.category !== 'all') {
            params = params.set('category', options.category);
        }
        return this.http.get<LibraryListResponse>(`${this.apiUrl}/library`, { params });
    }

    upload$(file: File, description = ''): Observable<{ status: string; item: LibraryItem }> {
        const form = new FormData();
        form.append('file', file);
        if (description) {
            form.append('description', description);
        }
        return this.http.post<{ status: string; item: LibraryItem }>(`${this.apiUrl}/library`, form);
    }

    content$(id: string): Observable<LibraryContentResponse> {
        return this.http.get<LibraryContentResponse>(`${this.apiUrl}/library/${encodeURIComponent(id)}/content`);
    }

    delete$(id: string): Observable<{ status: string; deleted: string }> {
        return this.http.delete<{ status: string; deleted: string }>(`${this.apiUrl}/library/${encodeURIComponent(id)}`);
    }

    blob$(item: LibraryItem): Observable<Blob> {
        return this.http.get(this.resolveUrl(item), { responseType: 'blob' });
    }

    resolveUrl(item: LibraryItem | null | undefined): string {
        if (!item?.url) {
            return '';
        }
        if (/^https?:\/\//i.test(item.url)) {
            return item.url;
        }
        return item.url.startsWith('/') ? item.url : `/${item.url}`;
    }
}
