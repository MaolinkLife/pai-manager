import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface UpdateReleaseInfo {
    tag: string;
    name: string;
    published_at: string;
    notes: string;
    url: string;
    zip_url: string;
}

export interface UpdateBranchRemote {
    version: string;
    behind: number | null;
    ahead: number | null;
    fetch_error?: string;
}

export interface UpdateCheckResult {
    status: string;
    repo: string;
    branch: string;
    local_version: string;
    git_available: boolean;
    git: { branch: string; sha: string; dirty: boolean } | null;
    release: UpdateReleaseInfo | null;
    branch_remote: UpdateBranchRemote | null;
    has_release_update: boolean;
    has_branch_update: boolean;
}

export interface UpdateRunResult {
    status: string;
    code?: string;
    message?: string;
    download_url?: string;
    updated?: boolean;
    target?: string;
    ref?: string;
    old_sha?: string;
    new_sha?: string;
    new_version?: string;
    needs_install?: boolean;
    needs_restart?: boolean;
}

@Injectable({ providedIn: 'root' })
export class UpdateService {
    constructor(private http: HttpClient) {}

    check$(): Observable<UpdateCheckResult> {
        return this.http.get<UpdateCheckResult>('/api/system/update/check');
    }

    run$(target: 'branch' | 'release'): Observable<UpdateRunResult> {
        return this.http.post<UpdateRunResult>('/api/system/update/run', { target });
    }
}
