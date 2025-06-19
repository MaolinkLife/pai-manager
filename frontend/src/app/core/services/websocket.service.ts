import { Injectable } from '@angular/core';
import { Subject } from 'rxjs';

@Injectable({
    providedIn: 'root'
})
export class WebsocketService {
    private socket: WebSocket | null = null;

    messages$ = new Subject<string | any>();

    connect(): void {
        this.socket = new WebSocket(`ws://${window.location.host}/api/ws`);

        this.socket.onopen = () => {
            console.log('[WS] ✅ Connected');
        };

        this.socket.onmessage = (event) => {
            console.log('[WS] Message:', event.data);
            this.messages$.next(event.data);
        };

        this.socket.onerror = (error) => {
            console.error('[WS] ❌ Error:', error);
        };

        this.socket.onclose = () => {
            console.log('[WS] ⚠️ Disconnected');
        };
    }

    send(message: string): void {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(message);
        } else {
            console.warn('[WS] ⛔ Not connected');
        }
    }

    disconnect(): void {
        if (this.socket) {
            this.socket.close();
            this.socket = null;
        }
    }
}
