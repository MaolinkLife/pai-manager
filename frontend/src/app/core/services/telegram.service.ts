import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface TelegramBridgeStatus {
    enabled: boolean;
    running: boolean;
    connected: boolean;
    authorized: boolean;
    auth_state: string;
    mode?: string | null;
    self_id?: number | null;
    self_username?: string | null;
    session_path?: string | null;
    queue_size?: number;
    queue_capacity?: number;
    chats_tracked?: number;
    started_at?: string | null;
    last_event_at?: string | null;
    last_error?: string | null;
    last_ping_ms?: number | null;
}

export interface TelegramAuthResult {
    ok: boolean;
    error?: string;
    state?: string;
    phone_number?: string;
    self_id?: number;
}

export interface TelegramChatPeer {
    chat_id: number;
    title: string;
    chat_kind: 'private' | 'group' | 'channel' | 'unknown' | string;
    username?: string | null;
    unread_count: number;
    is_allowed: boolean;
    blocked_reason?: string | null;
}

@Injectable({
    providedIn: 'root',
})
export class TelegramService {
    private readonly apiUrl = `${environment.apiBaseUrl}/telegram`;

    constructor(private readonly http: HttpClient) {}

    getStatus$(): Observable<{ status: string; telegram: TelegramBridgeStatus }> {
        return this.http.get<{ status: string; telegram: TelegramBridgeStatus }>(
            `${this.apiUrl}/status`
        );
    }

    start$(): Observable<{ status: string; started: boolean; telegram: TelegramBridgeStatus }> {
        return this.http.post<{ status: string; started: boolean; telegram: TelegramBridgeStatus }>(
            `${this.apiUrl}/start`,
            {}
        );
    }

    stop$(): Observable<{ status: string; was_running: boolean; telegram: TelegramBridgeStatus }> {
        return this.http.post<{ status: string; was_running: boolean; telegram: TelegramBridgeStatus }>(
            `${this.apiUrl}/stop`,
            {}
        );
    }

    ping$(): Observable<{ status: string; ping: { ok: boolean; latency_ms?: number; error?: string } }> {
        return this.http.post<{ status: string; ping: { ok: boolean; latency_ms?: number; error?: string } }>(
            `${this.apiUrl}/ping`,
            {}
        );
    }

    requestCode$(phoneNumber?: string): Observable<{ status: string; auth: TelegramAuthResult }> {
        return this.http.post<{ status: string; auth: TelegramAuthResult }>(
            `${this.apiUrl}/auth/request_code`,
            phoneNumber ? { phone_number: phoneNumber } : {}
        );
    }

    submitCode$(code: string): Observable<{ status: string; auth: TelegramAuthResult }> {
        return this.http.post<{ status: string; auth: TelegramAuthResult }>(
            `${this.apiUrl}/auth/submit_code`,
            { code }
        );
    }

    submitPassword$(password: string): Observable<{ status: string; auth: TelegramAuthResult }> {
        return this.http.post<{ status: string; auth: TelegramAuthResult }>(
            `${this.apiUrl}/auth/submit_password`,
            { password }
        );
    }

    listChats$(limit = 200, includeBlocked = true): Observable<{ status: string; chats: TelegramChatPeer[]; error?: string }> {
        return this.http.get<{ status: string; chats: TelegramChatPeer[]; error?: string }>(
            `${this.apiUrl}/chats`,
            { params: { limit, include_blocked: includeBlocked } as any }
        );
    }

    testPublicReflection$(sourceChatId?: number): Observable<{ status: string; probe: any }> {
        const payload = sourceChatId !== undefined ? { source_chat_id: sourceChatId } : {};
        return this.http.post<{ status: string; probe: any }>(
            `${this.apiUrl}/test/public_reflection`,
            payload
        );
    }

    testSendImage$(targetChatId?: number, prompt?: string, caption?: string): Observable<{ status: string; image_test: any }> {
        const payload: any = {};
        if (targetChatId !== undefined) {
            payload.target_chat_id = targetChatId;
        }
        if (prompt !== undefined) {
            payload.prompt = prompt;
        }
        if (caption !== undefined) {
            payload.caption = caption;
        }
        return this.http.post<{ status: string; image_test: any }>(
            `${this.apiUrl}/test/send_image`,
            payload
        );
    }
}
