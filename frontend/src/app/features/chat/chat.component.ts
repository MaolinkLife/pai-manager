import { AfterViewChecked, AfterViewInit, Component, ElementRef, HostListener, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { ApiService } from '../../core/services/api.service';
import { Message } from '../../core/models/message.model';
import { FormControl } from '@angular/forms';
import { ConfigService } from '../../core/services/config.service';
import { ProjectConfig } from './../../core/models/project-config.model';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { VoiceService } from '../../core/services/voice.service';

@Component({
    selector: 'app-chat',
    templateUrl: './chat.component.html',
    styleUrls: ['./chat.component.less']
})
export class ChatComponent implements OnInit, OnDestroy {
    @HostListener('document:click', ['$event'])
    onClickOutside(): void {
        this.activeDropdown = null;
    }

    chatInput = new FormControl('');
    chatHistory: Message[] = [];
    loading = false;

    userName: string = '';
    charName: string = '';

    config$: Observable<{ userName: string; charName: string } | null> | null = null;

    recording = false;

    activeDropdown: string | null = null;

    constructor(
        private apiService: ApiService,
        private configService: ConfigService,
        private voiceService: VoiceService,
    ) { }

    ngOnInit(): void {
        this.getSettings();
        this.loadHistory();
    }

    ngOnDestroy() { }

    scrollToBottom(): void {
        const tryScroll = () => {
            const anchor = document.getElementById('bottomAnchor');
            if (anchor) {
                anchor.scrollIntoView({ behavior: 'auto' });
            } else {
                // console.warn('⚠️ anchor не найден. Пробуем ещё раз...');
                setTimeout(() => requestAnimationFrame(tryScroll), 50);
            }
        };

        requestAnimationFrame(tryScroll);
    }

    toggleMessageMenu(msgId: string, event: Event): void {
        event.stopPropagation();
        this.activeDropdown = this.activeDropdown === msgId ? null : msgId;
    }

    copyMessage(msg: Message): void {
        navigator.clipboard.writeText(msg.content).then(() => {
            console.log('Скопировано!');
        });
    }

    toggleRecording() {
        if (!this.recording) {
            this.voiceService.startRecord$().subscribe(() => {
                this.recording = true;
                console.log({ start: 'recording' });
            });
        } else {
            this.voiceService.stopRecord$().subscribe((res) => {
                console.log({ stop_response: res });
                this.recording = false;

                const msg = res.data;

                if (msg && msg.content.trim()) {
                    // Добавляем как пользовательское сообщение
                    this.chatHistory.push(msg);
                    this.scrollToBottom();
                }
            });
        }
    }

    sendMessage(): void {
        const trimmed = this.chatInput.value?.trim();
        if (!trimmed) return;

        const userMessage: Message = { id: '', role: 'user', content: trimmed, timestamp: new Date().toISOString() };
        this.chatHistory.push(userMessage);
        this.chatInput.setValue('');
        this.loading = true;
        setTimeout(() => this.scrollToBottom(), 0);

        const message = {
            "history": [...this.chatHistory],
            "temp_level": 1,
            "max_tokens": 512
        }
        this.apiService.sendMessage$(message).subscribe({
            next: (res) => {
                this.chatHistory.push({ id: res.id, role: 'assistant', content: res.response, timestamp: new Date().toISOString() });
                this.loading = false;
                setTimeout(() => this.scrollToBottom(), 0);
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
                    setTimeout(() => this.scrollToBottom(), 0);
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

    playMessage(msg: Message) {
        console.log({
            msg
        });


        this.voiceService.playMessage(msg.id).subscribe((r) => {
            console.log({ r });

        })
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

        // Удалим последнее сообщение ассистента
        const lastIndex = this.chatHistory.findIndex(
            (msg, i) => msg.role === 'assistant' && i === this.chatHistory.length - 1
        );

        if (lastIndex !== -1) {
            this.chatHistory.splice(lastIndex, 1); // удалим сообщение из истории
        }

        setTimeout(() => this.scrollToBottom(), 0); // прокрутим вниз

        this.apiService.rerollMessage$(messageId).subscribe({
            next: (res) => {
                if (res.status === 'ok') {
                    this.loadHistory(); // получаем новую версию истории
                    this.loading = false;
                } else {
                    console.error('Ошибка реролла:', res.message || res);
                    this.loading = false;
                }
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

    stopVoice() {
        this.voiceService.stopPlay$().subscribe();
    }
}
