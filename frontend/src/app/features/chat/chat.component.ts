import { AfterViewChecked, AfterViewInit, Component, ElementRef, HostListener, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { ApiService } from '../../core/services/api.service';
import { Message } from '../../core/models/message.model';
import { FormControl } from '@angular/forms';
import { ConfigService } from '../../core/services/config.service';
import { ProjectConfig } from './../../core/models/project-config.model';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { VoiceService } from '../../core/services/voice.service';
import { WebsocketService } from '../../core/services/websocket.service';

function generateTempId(): string {
    if ((crypto as any).randomUUID) {
        return (crypto as any).randomUUID();
    }
    // fallback
    return 'temp-' + Math.random().toString(36).substr(2, 9);
}

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

    private currentStreamingMessage: Message | null = null;

    constructor(
        private apiService: ApiService,
        private configService: ConfigService,
        private voiceService: VoiceService,
        private websocketService: WebsocketService,
    ) { }

    ngOnInit(): void {
        this.getSettings();
        // this.loadHistory();

        this.websocketService.send(JSON.stringify({
            action: 'fetch_history',
            payload: { limit: 32 }
        }));

        this.websocketService.messages$.subscribe((rawMsg: string) => {
            let event: any;
            try {
                event = JSON.parse(rawMsg);
            } catch {
                console.warn('[WS] ⚠️ Received non-JSON message:', rawMsg);
                return;
            }

            switch (event.type) {
                case 'message_chunk':
                    // Убираем плашку "Печатает" при первом чанке
                    if (!this.currentStreamingMessage) {
                        this.loading = false;
                        const tempId = generateTempId();
                        this.currentStreamingMessage = {
                            id: tempId,
                            role: event.role,
                            content: event.content,
                            timestamp: new Date().toISOString(),
                            isPending: true
                        };
                        this.chatHistory.push(this.currentStreamingMessage);
                    } else {
                        this.currentStreamingMessage.content += event.content;
                    }
                    break;

                case 'message':
                    if (this.currentStreamingMessage) {
                        // обновляем последний pending сообщение
                        this.currentStreamingMessage.id = event.id || this.currentStreamingMessage.id;
                        this.currentStreamingMessage.isPending = false;
                        this.currentStreamingMessage.content = event.content;
                        this.currentStreamingMessage = null;
                    } else {
                        // если почему-то не было chunk'ов
                        this.chatHistory.push({
                            id: event.id,
                            role: event.role,
                            content: event.content,
                            timestamp: new Date().toISOString(),
                            isPending: false
                        });
                    }
                    this.loading = false;
                    break;

                case 'history':
                    this.chatHistory = event.items.map((m: any) => ({
                        ...m,
                        isPending: false
                    })).sort(
                        (a: any, b: any) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
                    );
                    break;

                case 'deleted':
                    if (event.chain) {
                        // Удаление цепочки
                        const deletedMsgIndex = this.chatHistory.findIndex(m => m.id === event.message_id);
                        if (deletedMsgIndex !== -1) {
                            const deletedMsg = this.chatHistory[deletedMsgIndex];
                            this.chatHistory.splice(deletedMsgIndex, 1);

                            // Если это пользовательское сообщение, удаляем следующее сообщение ассистента
                            if (deletedMsg.role === 'user') {
                                for (let i = deletedMsgIndex; i < this.chatHistory.length; i++) {
                                    if (this.chatHistory[i].role === 'assistant') {
                                        this.chatHistory.splice(i, 1);
                                        break;
                                    }
                                }
                            }
                        }
                    } else {
                        // Обычное удаление - удаляем только одно сообщение
                        this.chatHistory = this.chatHistory.filter(m => m.id !== event.message_id);
                    }
                    break;

                case 'reroll':
                    console.log('Reroll response:', event)
                    // Добавляем новое сообщение от reroll
                    this.chatHistory.push({
                        id: event.new_message.id,  // используем ID из ответа
                        role: event.new_message.role,
                        content: event.new_message.content,
                        timestamp: event.new_message.timestamp,
                        isPending: false
                    });
                    this.loading = false;
                    setTimeout(() => this.scrollToBottom(), 0);
                    break;

                case 'system':
                    if (event.event === 'stream_end') {
                        this.loading = false;
                        this.currentStreamingMessage = null;
                    }
                    break;

                case 'error':
                    console.error('[WS] ❌ Error from server:', event.message);
                    this.loading = false;
                    break;

                case 'ack_message':
                    // Найти сообщение с tempId и обновить его id
                    const idx = this.chatHistory.findIndex(m => m.id === event.tempId);
                    if (idx !== -1) {
                        this.chatHistory[idx].id = event.realId;
                        this.chatHistory[idx].isPending = false;
                    }
                    break;

                default:
                    console.warn('[WS] ⚠️ Unknown event:', event);
            }

            setTimeout(() => this.scrollToBottom(), 50);
        });
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

    toggleMessageMenu(msgId: string | null, event: Event): void {
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
                    // this.chatHistory.push(msg);
                    this.scrollToBottom();
                }
            });
        }
    }

    sendMessage(): void {
        const trimmed = this.chatInput.value?.trim();
        if (!trimmed) return;

        const tempId = generateTempId();
        const timestamp = new Date().toISOString();

        const userMessage: Message = {
            id: tempId,
            role: 'user',
            content: trimmed,
            timestamp,
            isPending: true
        };

        this.chatHistory.push(userMessage);

        this.chatInput.setValue('');
        this.loading = true;
        setTimeout(() => this.scrollToBottom(), 0);


        this.websocketService.send(JSON.stringify({
            action: 'send_message',
            payload: userMessage
        }));
    }

    loadHistory(): void {
        this.websocketService.send(JSON.stringify({
            action: 'fetch_history',
            payload: { limit: 32 }
        }));
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


        this.voiceService.playMessage(msg.id as string).subscribe((r) => {
            console.log({ r });
        })
    }

    deleteMessage(msg: Message, chain: boolean): void {
        if (!msg || !msg.id) return; // На всякий случай
        this.websocketService.send(JSON.stringify({
            action: 'delete_message',
            payload: { message_id: msg.id, chain }
        }));
    }

    rerollMessage(messageId: string | null): void {
        console.log('Reroll called with:', { messageId });

        // Если messageId не передан, ищем последнее сообщение ассистента
        if (!messageId) {
            // Ищем последнее сообщение ассистента (НЕ удаляем его!)
            for (let i = this.chatHistory.length - 1; i >= 0; i--) {
                if (this.chatHistory[i].role === 'assistant') {
                    messageId = this.chatHistory[i].id;
                    break;
                }
            }

            if (!messageId) {
                console.warn('No assistant message found for reroll');
                return;
            }
        }

        // Показываем "Печатает..." и убираем старое сообщение
        this.loading = true;

        // Удаляем последнее сообщение ассистента из фронтенда
        const lastAssistantIndex = this.chatHistory.map((msg, i) => ({ msg, i }))
            .reverse()
            .find(item => item.msg.role === 'assistant')?.i;

        if (lastAssistantIndex !== undefined) {
            this.chatHistory.splice(lastAssistantIndex, 1);
        }

        setTimeout(() => this.scrollToBottom(), 0);
        console.log('Sending reroll with ID:', messageId);
        // Отправляем reroll с ID существующего сообщения
        this.websocketService.send(JSON.stringify({
            action: 'reroll_message',
            payload: { message_id: messageId }
        }));
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
