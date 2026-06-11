import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

export interface KnowledgeCollection {
    id: string;
    name: string;
    description: string;
    enabled: boolean;
    embedding_provider: string;
    file_count: number;
    created_at: string;
    updated_at: string;
}

export interface KnowledgeFile {
    id: string;
    collection_id: string;
    media_id: string | null;
    name: string;
    mime_type: string;
    size: number;
    status: 'pending' | 'indexed' | 'error';
    error: string;
    chunk_count: number;
    indexed_at: string | null;
    created_at: string;
}

export interface KnowledgeMatch {
    text: string;
    similarity: number;
    collection_id: string;
    collection_name: string;
    file_id: string | null;
    file_name: string;
    chunk_index: number | null;
}

@Injectable({ providedIn: 'root' })
export class KnowledgeService {
    constructor(private http: HttpClient) {}

    collections$(): Observable<KnowledgeCollection[]> {
        return this.http
            .get<{ collections: KnowledgeCollection[] }>('/api/knowledge/collections')
            .pipe(map((response) => response.collections || []));
    }

    createCollection$(name: string, description = ''): Observable<KnowledgeCollection> {
        return this.http
            .post<{ collection: KnowledgeCollection }>('/api/knowledge/collections', { name, description })
            .pipe(map((response) => response.collection));
    }

    updateCollection$(
        id: string,
        patch: Partial<Pick<KnowledgeCollection, 'name' | 'description' | 'enabled'>>
    ): Observable<KnowledgeCollection> {
        return this.http
            .patch<{ collection: KnowledgeCollection }>(`/api/knowledge/collections/${id}`, patch)
            .pipe(map((response) => response.collection));
    }

    deleteCollection$(id: string): Observable<void> {
        return this.http.delete<void>(`/api/knowledge/collections/${id}`);
    }

    files$(collectionId: string): Observable<KnowledgeFile[]> {
        return this.http
            .get<{ files: KnowledgeFile[] }>(`/api/knowledge/collections/${collectionId}/files`)
            .pipe(map((response) => response.files || []));
    }

    addFile$(collectionId: string, mediaId: string): Observable<KnowledgeFile> {
        return this.http
            .post<{ file: KnowledgeFile }>(`/api/knowledge/collections/${collectionId}/files`, {
                media_id: mediaId,
            })
            .pipe(map((response) => response.file));
    }

    reindexFile$(fileId: string): Observable<KnowledgeFile> {
        return this.http
            .post<{ file: KnowledgeFile }>(`/api/knowledge/files/${fileId}/reindex`, {})
            .pipe(map((response) => response.file));
    }

    removeFile$(fileId: string): Observable<void> {
        return this.http.delete<void>(`/api/knowledge/files/${fileId}`);
    }

    reindexCollection$(collectionId: string): Observable<KnowledgeFile[]> {
        return this.http
            .post<{ files: KnowledgeFile[] }>(`/api/knowledge/collections/${collectionId}/reindex`, {})
            .pipe(map((response) => response.files || []));
    }

    search$(query: string, topK = 0): Observable<KnowledgeMatch[]> {
        return this.http
            .get<{ matches: KnowledgeMatch[] }>('/api/knowledge/search', {
                params: { q: query, top_k: String(topK) },
            })
            .pipe(map((response) => response.matches || []));
    }
}
