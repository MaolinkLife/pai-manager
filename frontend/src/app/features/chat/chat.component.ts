import { Component, OnInit } from '@angular/core';
import { ApiService } from '../../core/services/api.service';
import { Message } from '../../core/models/message.model';
import { FormControl } from '@angular/forms';
import { ConfigService } from '../../core/services/config.service';
import { ProjectConfig } from './../../core/models/project-config.model';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';

@Component({
    selector: 'app-chat',
    templateUrl: './chat.component.html',
    styleUrls: ['./chat.component.less']
})
export class ChatComponent implements OnInit {
    chatInput = new FormControl('');
    chatHistory: Message[] = [];
    loading = false;

    userName: string = '';
    charName: string = '';

    config$: Observable<{ userName: string; charName: string } | null> | null = null;

    constructor(private apiService: ApiService, private configService: ConfigService) { }

    ngOnInit(): void {
        this.getSettings();
        this.loadHistory();
    }

    sendMessage(): void {
        const trimmed = this.chatInput.value?.trim();
        if (!trimmed) return;

        const userMessage: Message = { id: '', role: 'user', content: trimmed, timestamp: new Date().toISOString() };
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
                this.chatHistory.push({ id: res.id, role: 'assistant', content: res.response, timestamp: new Date().toISOString() });
                this.loading = false;
            },
            error: (err) => {
                this.chatHistory.push({
                    id: '',
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

    getSettings(): void {
        this.config$ = this.configService.getConfig$().pipe(
            map((config: ProjectConfig | null) => {
                if (!config) {
                    return null;
                }

                const { userName, charName } = config;
                this.userName = userName;
                this.charName = charName;

                return {
                    userName,
                    charName
                }
            })
        )
    }

    deleteMessage(msg: Message, chain: boolean): void {
        if (!msg || !msg.id) return; // На всякий случай

        this.apiService.deleteMessage$(msg.id, chain).subscribe({
            next: (res) => {
                if (res.status === 'ok') {
                    // Обновим локально
                    this.chatHistory = this.chatHistory.filter(m => {
                        if (!chain) return m.id !== msg.id;
                        if (m.id === msg.id) return false;

                        // Если цепочка: удалим следующее сообщение от ассистента по таймстампу
                        return !(m.role === 'assistant' && m.timestamp === msg.timestamp);
                    });
                } else {
                    console.warn('Не удалось удалить сообщение:', res);
                }

                this.loadHistory();
            },
            error: (err) => {
                console.error('Ошибка при удалении:', err);
            }
        });
    }

    rerollMessage(messageId: string): void {
        if (!messageId) return;

        this.loading = true;

        this.apiService.rerollMessage$(messageId).subscribe({
            next: (res) => {
                if (res.status === 'ok') {
                    // Обновляем историю после реролла
                    this.loadHistory();
                } else {
                    console.error('Ошибка реролла:', res.message || res);
                }
                this.loading = false;
            },
            error: (err) => {
                console.error('Ошибка при реролле:', err);
                this.loading = false;
            },
        });
    }

    shouldShowReroll(msg: Message, index: number): boolean {
        // Только если это ассистент и это последнее сообщение в списке
        return msg.role === 'assistant' && index === this.chatHistory.length - 1;
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
