import { Component, HostListener, OnDestroy, OnInit } from '@angular/core';
import { FormControl } from '@angular/forms';
import { Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { Message } from '../../core/models/message.model';
import { ProjectConfig } from './../../core/models/project-config.model';
import { ApiService } from '../../core/services/api.service';
import { ConfigService } from '../../core/services/config.service';
import { VoiceService } from '../../core/services/voice.service';
import { WebsocketService } from '../../core/services/websocket.service';

function generateTempId(): string {
    if ((crypto as any).randomUUID) {
        return (crypto as any).randomUUID();
    }
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
        this.showEmojiPicker = false;
    }

    showEmojiPicker = false;
    allEmojis = [
        // Smileys
        { symbol: '😀', name: 'grinning face', category: 'smileys' },
        { symbol: '😃', name: 'grinning face with big eyes', category: 'smileys' },
        { symbol: '😄', name: 'grinning face with smiling eyes', category: 'smileys' },
        { symbol: '😁', name: 'beaming face with smiling eyes', category: 'smileys' },
        { symbol: '😆', name: 'grinning squinting face', category: 'smileys' },
        { symbol: '😅', name: 'grinning face with sweat', category: 'smileys' },
        { symbol: '🤣', name: 'rolling on the floor laughing', category: 'smileys' },
        { symbol: '😂', name: 'face with tears of joy', category: 'smileys' },
        { symbol: '🙂', name: 'slightly smiling face', category: 'smileys' },
        { symbol: '🙃', name: 'upside-down face', category: 'smileys' },
        { symbol: '😉', name: 'winking face', category: 'smileys' },
        { symbol: '😊', name: 'smiling face with smiling eyes', category: 'smileys' },
        { symbol: '😇', name: 'smiling face with halo', category: 'smileys' },

        // People
        { symbol: '👋', name: 'waving hand', category: 'people' },
        { symbol: '🤚', name: 'raised back of hand', category: 'people' },
        { symbol: '🖐️', name: 'hand with fingers splayed', category: 'people' },
        { symbol: '✋', name: 'raised hand', category: 'people' },
        { symbol: '🖖', name: 'vulcan salute', category: 'people' },
        { symbol: '👌', name: 'OK hand', category: 'people' },
        { symbol: '🤌', name: 'pinched fingers', category: 'people' },
        { symbol: '🤏', name: 'pinching hand', category: 'people' },
        { symbol: '✌️', name: 'victory hand', category: 'people' },
        { symbol: '🤞', name: 'crossed fingers', category: 'people' },
        { symbol: '🤟', name: 'love-you gesture', category: 'people' },
        { symbol: '🤘', name: 'sign of the horns', category: 'people' },
        { symbol: '🤙', name: 'call me hand', category: 'people' },

        // Nature
        { symbol: '🐶', name: 'dog face', category: 'nature' },
        { symbol: '🐱', name: 'cat face', category: 'nature' },
        { symbol: '🐭', name: 'mouse face', category: 'nature' },
        { symbol: '🐹', name: 'hamster', category: 'nature' },
        { symbol: '🐰', name: 'rabbit face', category: 'nature' },
        { symbol: '🦊', name: 'fox', category: 'nature' },
        { symbol: '🐻', name: 'bear', category: 'nature' },
        { symbol: '🐼', name: 'panda', category: 'nature' },
        { symbol: '🐨', name: 'koala', category: 'nature' },
        { symbol: '🐯', name: 'tiger face', category: 'nature' },
        { symbol: '🦁', name: 'lion', category: 'nature' },
        { symbol: '🐮', name: 'cow face', category: 'nature' },
        { symbol: '🐷', name: 'pig face', category: 'nature' },

        // Food
        { symbol: '🍇', name: 'grapes', category: 'food' },
        { symbol: '🍈', name: 'melon', category: 'food' },
        { symbol: '🍉', name: 'watermelon', category: 'food' },
        { symbol: '🍊', name: 'tangerine', category: 'food' },
        { symbol: '🍋', name: 'lemon', category: 'food' },
        { symbol: '🍌', name: 'banana', category: 'food' },
        { symbol: '🍍', name: 'pineapple', category: 'food' },
        { symbol: '🥭', name: 'mango', category: 'food' },
        { symbol: '🍎', name: 'red apple', category: 'food' },
        { symbol: '🍏', name: 'green apple', category: 'food' },
        { symbol: '🍐', name: 'pear', category: 'food' },
        { symbol: '🍑', name: 'peach', category: 'food' },
        { symbol: '🍒', name: 'cherries', category: 'food' },

        // Activity
        { symbol: '⚽', name: 'soccer ball', category: 'activity' },
        { symbol: '🏀', name: 'basketball', category: 'activity' },
        { symbol: '🏈', name: 'american football', category: 'activity' },
        { symbol: '⚾', name: 'baseball', category: 'activity' },
        { symbol: '🎾', name: 'tennis', category: 'activity' },
        { symbol: '🏐', name: 'volleyball', category: 'activity' },
        { symbol: '🏉', name: 'rugby football', category: 'activity' },
        { symbol: '🎱', name: 'pool 8 ball', category: 'activity' },
        { symbol: '🏓', name: 'ping pong', category: 'activity' },
        { symbol: '🏸', name: 'badminton', category: 'activity' },
        { symbol: '🥅', name: 'goal net', category: 'activity' },
        { symbol: '🏒', name: 'ice hockey', category: 'activity' },
        { symbol: '🥍', name: 'lacrosse', category: 'activity' },

        // Travel
        { symbol: '🚗', name: 'automobile', category: 'travel' },
        { symbol: '🚕', name: 'taxi', category: 'travel' },
        { symbol: '🚙', name: 'sport utility vehicle', category: 'travel' },
        { symbol: '🚌', name: 'bus', category: 'travel' },
        { symbol: '🚎', name: 'trolleybus', category: 'travel' },
        { symbol: '🏎️', name: 'racing car', category: 'travel' },
        { symbol: '🚓', name: 'police car', category: 'travel' },
        { symbol: '🚑', name: 'ambulance', category: 'travel' },
        { symbol: '🚒', name: 'fire engine', category: 'travel' },
        { symbol: '🚐', name: 'minibus', category: 'travel' },
        { symbol: '🚚', name: 'delivery truck', category: 'travel' },
        { symbol: '🚛', name: 'articulated lorry', category: 'travel' },
        { symbol: '🚜', name: 'tractor', category: 'travel' },

        // Objects
        { symbol: '⌚', name: 'watch', category: 'objects' },
        { symbol: '📱', name: 'mobile phone', category: 'objects' },
        { symbol: '💻', name: 'laptop', category: 'objects' },
        { symbol: '⌨️', name: 'keyboard', category: 'objects' },
        { symbol: '🖥️', name: 'desktop computer', category: 'objects' },
        { symbol: '🖨️', name: 'printer', category: 'objects' },
        { symbol: '🖱️', name: 'computer mouse', category: 'objects' },
        { symbol: '🖲️', name: 'trackball', category: 'objects' },
        { symbol: '🕹️', name: 'joystick', category: 'objects' },
        { symbol: '🗜️', name: 'clamp', category: 'objects' },
        { symbol: '💽', name: 'computer disk', category: 'objects' },
        { symbol: '💾', name: 'floppy disk', category: 'objects' },
        { symbol: '💿', name: 'optical disk', category: 'objects' },

        // Symbols
        { symbol: '❤️', name: 'red heart', category: 'symbols' },
        { symbol: '🧡', name: 'orange heart', category: 'symbols' },
        { symbol: '💛', name: 'yellow heart', category: 'symbols' },
        { symbol: '💚', name: 'green heart', category: 'symbols' },
        { symbol: '💙', name: 'blue heart', category: 'symbols' },
        { symbol: '💜', name: 'purple heart', category: 'symbols' },
        { symbol: '🖤', name: 'black heart', category: 'symbols' },
        { symbol: '🤍', name: 'white heart', category: 'symbols' },
        { symbol: '🤎', name: 'brown heart', category: 'symbols' },
        { symbol: '💔', name: 'broken heart', category: 'symbols' },
        { symbol: '❣️', name: 'heart exclamation', category: 'symbols' },
        { symbol: '💕', name: 'two hearts', category: 'symbols' },
        { symbol: '💞', name: 'revolving hearts', category: 'symbols' }
    ];


    emojiSearchTerm = '';
    selectedEmojiCategory = 'smileys';
    filteredEmojis: any[] = [];

    emojiCategories = [
        { name: 'smileys', icon: '😀', label: 'Смайлики' },
        { name: 'people', icon: '👋', label: 'Люди' },
        { name: 'nature', icon: '🐶', label: 'Природа' },
        { name: 'food', icon: '🍎', label: 'Еда' },
        { name: 'activity', icon: '⚽', label: 'Активность' },
        { name: 'travel', icon: '🚗', label: 'Путешествия' },
        { name: 'objects', icon: '⌚', label: 'Объекты' },
        { name: 'symbols', icon: '❤️', label: 'Символы' }
    ];


    // Pagination properties
    hasMoreMessages = true;
    isLoadingHistory = false;
    currentOffset = 0;
    readonly MESSAGES_PER_PAGE = 32;
    emojiDropdownPosition = { x: 0, y: 0 };
    chatInput = new FormControl('');
    chatHistory: Message[] = [];
    loading = false;
    chatInputValue: string = '';
    userName: string = '';
    charName: string = '';

    config$: Observable<{ userName: string; charName: string } | null> | null = null;

    recording = false;
    activeDropdown: string | null = null;
    currentPlayingMessage: string | null = null;
    private currentStreamingMessage: Message | null = null;

    constructor(
        private apiService: ApiService,
        private configService: ConfigService,
        private voiceService: VoiceService,
        private websocketService: WebsocketService,
    ) { }

    ngOnInit(): void {
        this.getSettings();
        this.loadHistory();

        this.websocketService.messages$.subscribe((rawMsg: string) => {
            let event: any;
            try {
                event = JSON.parse(rawMsg);
            } catch {
                console.warn('[WS] ⚠️ Received non-JSON message:', rawMsg);
                this.isLoadingHistory = false;
                return;
            }

            switch (event.type) {
                case 'message_chunk':
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
                        this.currentStreamingMessage.id = event.id || this.currentStreamingMessage.id;
                        this.currentStreamingMessage.isPending = false;
                        this.currentStreamingMessage.content = event.content;
                        this.currentStreamingMessage = null;
                    } else {
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
                    const newMessages = event.items.map((m: any) => ({
                        ...m,
                        isPending: false
                    })).sort(
                        (a: any, b: any) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
                    );

                    if (this.isLoadingHistory) {
                        // Append older messages to the beginning
                        this.chatHistory = [...newMessages, ...this.chatHistory];
                        this.currentOffset += newMessages.length;
                        this.hasMoreMessages = newMessages.length === this.MESSAGES_PER_PAGE;
                        this.isLoadingHistory = false;
                    } else {
                        // Initial load
                        this.chatHistory = newMessages;
                        this.currentOffset = newMessages.length;
                        this.hasMoreMessages = newMessages.length === this.MESSAGES_PER_PAGE;
                    }
                    break;

                case 'deleted':
                    if (event.chain) {
                        const deletedMsgIndex = this.chatHistory.findIndex(m => m.id === event.message_id);
                        if (deletedMsgIndex !== -1) {
                            const deletedMsg = this.chatHistory[deletedMsgIndex];
                            this.chatHistory.splice(deletedMsgIndex, 1);

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
                        this.chatHistory = this.chatHistory.filter(m => m.id !== event.message_id);
                    }
                    break;

                case 'reroll':
                    this.chatHistory.push({
                        id: event.new_message.id,
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

    isMessageStreaming(msg: Message): boolean {
        return msg.isPending === true && msg.role === 'assistant';
    }

    toggleEmojiDropdown(event: Event): void {
        event.stopPropagation();

        if (!this.showEmojiPicker) {
            // Получаем кнопку и ее позицию
            const button = event.target as HTMLElement;
            const rect = button.getBoundingClientRect();

            // Вычисляем позицию дропдауна
            const dropdownWidth = 320;
            const dropdownHeight = 300;

            // Позиция по X - выравниваем по левому краю кнопки
            let x = rect.left;

            // Проверяем, не выходит ли дропдаун за правую границу экрана
            if (x + dropdownWidth > window.innerWidth) {
                x = window.innerWidth - dropdownWidth;
            }

            // Проверяем, не выходит ли дропдаун за левую границу экрана
            if (x < 0) {
                x = 0;
            }

            // Позиция по Y - показываем над кнопкой
            let y = rect.top - dropdownHeight - 10;

            // Если нет места сверху, показываем под кнопкой
            if (y < 0) {
                y = rect.bottom + 10;
            }

            this.emojiDropdownPosition = { x, y };
        }

        this.showEmojiPicker = !this.showEmojiPicker;
        this.activeDropdown = this.showEmojiPicker ? 'emoji' : null;

        if (this.showEmojiPicker) {
            this.emojiSearchTerm = '';
            this.filteredEmojis = this.allEmojis.filter(e => e.category === 'smileys');
        }
    }

    // Load more messages with cumulative offset
    loadMoreHistory(): void {
        if (!this.hasMoreMessages || this.isLoadingHistory) return;

        this.isLoadingHistory = true;

        this.websocketService.send(JSON.stringify({
            action: 'fetch_history',
            payload: {
                limit: this.MESSAGES_PER_PAGE,
                offset: this.currentOffset // Правильный offset - не увеличиваем лимит, а сдвигаем позицию
            }
        }));
    }

    addEmoji(emoji: string): void {
        const currentValue = this.chatInput.value || '';
        const newValue = currentValue + emoji;
        this.chatInput.setValue(newValue);
        this.showEmojiPicker = false;

        setTimeout(() => {
            const textarea = document.querySelector('.chat-input') as HTMLTextAreaElement;
            if (textarea) {
                textarea.focus();
                this.onKeyUp();
            }
        });
    }

    onEmojiSearchInput(event: any): void {
        this.emojiSearchTerm = event.target.value;
        this.filterEmojis();
    }

    filterEmojis(): void {
        if (!this.emojiSearchTerm) {
            this.filteredEmojis = this.allEmojis.filter(e => e.category === this.selectedEmojiCategory);
            return;
        }

        const term = this.emojiSearchTerm.toLowerCase();
        this.filteredEmojis = this.allEmojis.filter(emoji =>
            emoji.name.toLowerCase().includes(term) ||
            emoji.symbol.includes(this.emojiSearchTerm)
        );
    }


    selectEmojiCategory(category: string): void {
        this.selectedEmojiCategory = category;
        this.emojiSearchTerm = '';
        this.filteredEmojis = this.allEmojis.filter(e => e.category === category);
    }

    loadHistory(): void {
        this.currentOffset = 0;
        this.hasMoreMessages = true;
        this.isLoadingHistory = false;

        this.websocketService.send(JSON.stringify({
            action: 'fetch_history',
            payload: { limit: this.MESSAGES_PER_PAGE }
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

    // Message handling methods
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
        this.chatInputValue = '';
        this.chatInput.setValue('');
        this.loading = true;
        setTimeout(() => this.scrollToBottom(), 0);

        this.websocketService.send(JSON.stringify({
            action: 'send_message',
            payload: userMessage
        }));
    }

    copyMessage(msg: Message): void {
        navigator.clipboard.writeText(msg.content).then(() => {
            console.log('Copied!');
        });
    }

    deleteMessage(msg: Message, chain: boolean): void {
        if (!msg || !msg.id) return;
        this.websocketService.send(JSON.stringify({
            action: 'delete_message',
            payload: { message_id: msg.id, chain }
        }));
    }

    rerollMessage(messageId: string | null): void {
        if (!messageId) {
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

        this.loading = true;

        const lastAssistantIndex = this.chatHistory.map((msg, i) => ({ msg, i }))
            .reverse()
            .find(item => item.msg.role === 'assistant')?.i;

        if (lastAssistantIndex !== undefined) {
            this.chatHistory.splice(lastAssistantIndex, 1);
        }

        setTimeout(() => this.scrollToBottom(), 0);

        this.websocketService.send(JSON.stringify({
            action: 'reroll_message',
            payload: { message_id: messageId }
        }));
    }

    // Voice methods
    toggleRecording() {
        if (!this.recording) {
            this.voiceService.startRecord$().subscribe(() => {
                this.recording = true;
            });
        } else {
            this.voiceService.stopRecord$().subscribe((res) => {
                this.recording = false;
                const msg = res.data;
                if (msg && msg.content.trim()) {
                    this.scrollToBottom();
                }
            });
        }
    }

    toggleVoice(msgId: string | null | undefined): void {
        if (!msgId) return;

        if (this.currentPlayingMessage === msgId) {
            this.voiceService.stopPlay$().subscribe();
            this.currentPlayingMessage = null;
        } else {
            this.voiceService.playMessage(msgId).subscribe();
            this.currentPlayingMessage = msgId;
        }
    }

    stopVoice() {
        this.voiceService.stopPlay$().subscribe();
    }

    playMessage(msg: Message) {
        this.voiceService.playMessage(msg.id as string).subscribe();
    }

    // UI methods
    onKeyDown(event: KeyboardEvent): void {
        if (event.key === 'Enter' && event.shiftKey) {
            // Allow line break
        } else if (event.key === 'Enter') {
            event.preventDefault();
            this.sendMessage();
        }
    }

    onKeyUp(): void {
        const textarea = document.querySelector('.chat-input') as HTMLTextAreaElement;
        if (textarea) {
            textarea.style.height = 'auto';
            textarea.style.height = `${textarea.scrollHeight}px`;
        }
    }

    scrollToBottom(): void {
        const tryScroll = () => {
            const anchor = document.getElementById('bottomAnchor');
            if (anchor) {
                anchor.scrollIntoView({ behavior: 'auto' });
            } else {
                setTimeout(() => requestAnimationFrame(tryScroll), 50);
            }
        };
        requestAnimationFrame(tryScroll);
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

    // Unused methods - can be removed if not needed
    toggleMessageMenu(msgId: string | null, event: Event): void {
        event.stopPropagation();
        this.activeDropdown = this.activeDropdown === msgId ? null : msgId;
    }

    editMessage(msg: Message): void {
        console.log('Editing:', msg);
    }

    toggleAttachDropdown(): void {
        console.log('Opening attachments dropdown...');
    }

    shouldShowReroll(msg: Message, index: number): boolean {
        return msg.role === 'assistant' && index === this.chatHistory.length - 1;
    }
}
