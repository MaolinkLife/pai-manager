import { Component, OnInit } from '@angular/core';
import { ApiService } from '../../core/services/api.service';
import { Message } from '../../core/models/message.model';
import { FormControl } from '@angular/forms';

@Component({
    selector: 'app-chat',
    templateUrl: './chat.component.html',
    styleUrls: ['./chat.component.less']
})
export class ChatComponent implements OnInit {
    chatInput = new FormControl('');
    chatHistory: Message[] = [];
    loading = false;

    constructor(private apiService: ApiService) { }

    ngOnInit(): void {
        this.loadHistory();
    }

    sendMessage(): void {
        const trimmed = this.chatInput.value?.trim();
        if (!trimmed) return;

        const userMessage: Message = { role: 'user', content: trimmed, timestamp: new Date().toISOString() };
        this.chatHistory.push(userMessage);
        this.chatInput.setValue('');
        this.loading = true;

        const message = {
            "history": [...this.chatHistory],
            "temp_level": 1,
            "max_tokens": 512
        }
        this.apiService.sendMessage$(message).subscribe({
            next: (res) => {
                this.chatHistory.push({ role: 'assistant', content: res.response, timestamp: new Date().toISOString() });
                this.loading = false;
            },
            error: (err) => {
                this.chatHistory.push({
                    role: 'assistant',
                    content: '[Ошибка получения ответа]',
                    timestamp: new Date().toISOString(),
                });
                this.loading = false;
                console.error(err);
            },
        });
    }

    loadHistory(): void {
        this.apiService.getChatHistory$().subscribe({
            next: (res) => {
                if (res.status === 'ok' && Array.isArray(res.history)) {
                    this.chatHistory = res.history
                        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())
                        .map((msg) => ({ ...msg }));
                }
            },
            error: (err) => {
                console.error('Ошибка загрузки истории:', err);
            },
        });
    }

    formatTimestamp(isoDate?: string): string {
        if (!isoDate) return '';

        const date = new Date(isoDate);
        const now = new Date();

        const isToday =
            date.getDate() === now.getDate() &&
            date.getMonth() === now.getMonth() &&
            date.getFullYear() === now.getFullYear();

        const time = date.toLocaleTimeString([], {
            hour: '2-digit',
            minute: '2-digit',
        });

        if (isToday) return time;

        const dateStr = date.toLocaleDateString(undefined, {
            day: 'numeric',
            month: 'long',
            year: 'numeric',
        });

        return `${dateStr} ${time}`;
    }
}
