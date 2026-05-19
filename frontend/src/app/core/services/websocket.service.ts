import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';
import { AuthService } from './auth.service';

export interface BufferedWebsocketMessage {
    sequence: number;
    data: string;
    receivedAt: number;
}

@Injectable({
    providedIn: 'root'
})
export class WebsocketService {
    private static readonly EVENT_BUFFER_LIMIT = 5000;

    private socket: WebSocket | null = null;
    private messageQueue: string[] = [];
    private readonly eventBuffer: BufferedWebsocketMessage[] = [];
    private readonly consumerCursors = new Map<string, number>();
    private eventSequence = 0;
    private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    private reconnectAttempts = 0;
    private manualDisconnect = false;
    private connecting = false;
    private readonly reconnectBaseDelayMs = 1000;
    private readonly reconnectMaxDelayMs = 10000;

    messages$ = new Subject<string>();
    bufferedMessages$ = new Subject<BufferedWebsocketMessage>();
    constructor(private authService: AuthService) { }

    connect(): void {
        if (this.socket || this.connecting) return; // чтобы второй раз не коннектился

        this.manualDisconnect = false;
        this.clearReconnectTimer();
        this.connecting = true;

        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const token = this.authService.getAccessToken();
        const query = token ? `?access_token=${encodeURIComponent(token)}` : '';
        this.socket = new WebSocket(`${protocol}://${window.location.host}/api/ws${query}`);

        this.socket.onopen = () => {
            this.connecting = false;
            this.reconnectAttempts = 0;
            console.log('[WS] ✅ Connected');
            const sock = this.socket;  // сохранили ссылку
            while (this.messageQueue.length > 0) {
                const msg = this.messageQueue.shift();
                if (msg && sock) sock.send(msg);
            }
        };

        this.socket.onmessage = (event) => this.recordIncomingMessage(String(event.data || ''));

        this.socket.onerror = (error) => {
            console.error('[WS] ❌ Error:', error);
        };

        this.socket.onclose = () => {
            this.connecting = false;
            console.log('[WS] ⚠️ Disconnected');
            this.socket = null;
            if (!this.manualDisconnect && this.shouldAutoReconnect()) {
                this.scheduleReconnect();
            }
        };
    }

    isConnected(): boolean {
        return !!this.socket && this.socket.readyState === WebSocket.OPEN;
    }

    send(message: string): void {
        const socket = this.socket;
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(message);
        } else {
            console.warn('[WS] ⛔ Not connected yet, queueing message');
            this.messageQueue.push(message);
            if (this.shouldAutoReconnect()) {
                this.connect();
            }
        }
    }

    disconnect(): void {
        this.manualDisconnect = true;
        this.clearReconnectTimer();
        this.connecting = false;
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
    }

    reconnect(): void {
        this.disconnect();
        this.connect();
    }

    getLatestSequence(): number {
        return this.eventSequence;
    }

    getBufferedMessagesAfter(sequence: number): BufferedWebsocketMessage[] {
        const cursor = Math.max(0, Number(sequence || 0));
        return this.eventBuffer.filter((item) => item.sequence > cursor);
    }

    getConsumerCursor(consumer: string): number {
        return this.consumerCursors.get(consumer) || 0;
    }

    setConsumerCursor(consumer: string, sequence: number): void {
        this.consumerCursors.set(consumer, Math.max(0, Number(sequence || 0)));
    }

    private recordIncomingMessage(data: string): void {
        const event: BufferedWebsocketMessage = {
            sequence: ++this.eventSequence,
            data,
            receivedAt: Date.now(),
        };
        this.eventBuffer.push(event);
        if (this.eventBuffer.length > WebsocketService.EVENT_BUFFER_LIMIT) {
            this.eventBuffer.splice(0, this.eventBuffer.length - WebsocketService.EVENT_BUFFER_LIMIT);
        }
        this.messages$.next(event.data);
        this.bufferedMessages$.next(event);
    }

    private shouldAutoReconnect(): boolean {
        return this.authService.isAuthenticated() || this.authService.isAnonymousMode();
    }

    private scheduleReconnect(): void {
        if (this.reconnectTimer) {
            return;
        }
        const delay = Math.min(
            this.reconnectBaseDelayMs * Math.max(1, 2 ** this.reconnectAttempts),
            this.reconnectMaxDelayMs
        );
        this.reconnectAttempts += 1;
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            if (!this.socket && this.shouldAutoReconnect()) {
                this.connect();
            }
        }, delay);
    }

    private clearReconnectTimer(): void {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = null;
        }
    }
}
