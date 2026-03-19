import { Component, DestroyRef, ElementRef, HostListener, OnDestroy, OnInit, ViewChild, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { UntypedFormControl } from '@angular/forms';
import { Observable } from 'rxjs';
import { finalize, map } from 'rxjs/operators';
import { Message, MessageMedia, MessageMediaCategory } from '../../core/models/message.model';
import { ProjectConfig } from '../../core/models/project-config.model';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { ConfigService } from '../../core/services/config.service';
import { VoiceModeResponse, VoiceService } from '../../core/services/voice.service';
import { WebsocketService } from '../../core/services/websocket.service';
import { NotificationService } from '../../shared/components/notification/notification.service';

function generateTempId(): string {
    if ((crypto as any).randomUUID) {
        return (crypto as any).randomUUID();
    }
    return 'temp-' + Math.random().toString(36).substr(2, 9);
}

const DEFAULT_MIME_TYPE = 'application/octet-stream';
const DOCUMENT_EXTENSIONS = new Set(['pdf', 'doc', 'docx', 'txt', 'rtf', 'xls', 'xlsx', 'csv', 'ppt', 'pptx']);

type RuntimeStatus = 'started' | 'running' | 'stopping' | 'stopped' | 'completed' | 'error' | 'no_active_run';

interface RuntimeTraceEntry {
    stage: string;
    state: string;
    timestamp?: string;
    elapsedMs?: number;
    details?: Record<string, any>;
}

interface RuntimeState {
    runId: string;
    status: RuntimeStatus;
    startedAt?: string;
    finishedAt?: string;
    elapsedMs?: number;
    model?: string;
    usage?: Record<string, any> | null;
    meta?: Record<string, any> | null;
    reasoningElapsedMs?: number;
    detailsOpen?: boolean;
    traces: RuntimeTraceEntry[];
}

interface RuntimeStageView {
    id: string;
    label: string;
    state: 'pending' | 'active' | 'done';
    elapsedMs?: number;
}

const RUNTIME_STAGE_GROUPS: Array<{ id: string; label: string; keys: string[]; optional?: boolean }> = [
    { id: 'analysis', label: 'Провожу анализ', keys: ['analysis'] },
    { id: 'memory', label: 'Ищу в памяти', keys: ['memory'] },
    { id: 'instructions', label: 'Собираю инструкции', keys: ['decision', 'moral', 'prompt'] },
    { id: 'vision', label: 'Обрабатываю медиа', keys: ['vision'], optional: true },
    { id: 'generation', label: 'Генерирую ответ', keys: ['generation'] },
];

@Component({
    selector: 'app-chat',
    templateUrl: './chat.component.html',
    styleUrls: ['./chat.component.less']
})
export class ChatComponent implements OnInit, OnDestroy {
    private readonly destroyRef = inject(DestroyRef);

    @HostListener('document:click', ['$event'])
    onClickOutside(): void {
        this.activeDropdown = null;
        this.showEmojiPicker = false;
    }

    // Pagination properties
    hasMoreMessages = true;
    isLoadingHistory = false;
    currentOffset = 0;
    readonly MESSAGES_PER_PAGE = 32;

    showEmojiPicker = false;
    emojiDropdownPosition: { x: number; y: number } = { x: 0, y: 0 };
    emojiPickerMode: 'dropdown' | 'side-panel' = 'side-panel';
    emojiPickerSide: 'left' | 'right' | 'top' | 'bottom' = 'right';
    readonly emojiPanelWidth = 360;
    readonly emojiPanelHeight = 360;
    chatInput = new UntypedFormControl('');
    chatHistory: Message[] = [];
    loading = false;
    chatInputValue: string = '';
    userName: string = '';
    charName: string = '';
    attachments: MessageMedia[] = [];
    selectedMedia: MessageMedia | null = null;
    isProcessingAttachments = false;

    config$: Observable<{ userName: string; charName: string } | null> | null = null;

    recording = false;
    voiceModeEnabled = false;
    voiceModeLoading = false;
    activeDropdown: string | null = null;
    currentPlayingMessage: string | null = null;
    activeGenerationRunId: string | null = null;
    ttsEnabled = false;
    editingMessageId: string | null = null;
    editMessageControl = new UntypedFormControl('');
    private currentStreamingMessage: Message | null = null;
    private runtimeByRunId = new Map<string, RuntimeState>();
    private playbackResetTimer: ReturnType<typeof setTimeout> | null = null;
    @ViewChild('fileInput') private fileInputRef?: ElementRef<HTMLInputElement>;
    @ViewChild('chatTextarea') private chatTextareaRef?: ElementRef<HTMLTextAreaElement>;

    constructor(
        private apiService: ApiService,
        private authService: AuthService,
        private configService: ConfigService,
        private voiceService: VoiceService,
        private websocketService: WebsocketService,
        private notificationService: NotificationService
    ) { }

    ngOnInit(): void {
        this.getSettings();
        this.loadHistory();
        this.fetchVoiceModeStatus();

        this.websocketService.messages$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((rawMsg: string) => {
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
                    if (event.run_id) {
                        this.activeGenerationRunId = event.run_id;
                    }
                    if (!this.currentStreamingMessage) {
                        this.loading = false;
                        const tempId = generateTempId();
                        const runtime = this.ensureRuntime(event.run_id);
                        this.currentStreamingMessage = {
                            id: tempId,
                            role: event.role,
                            content: event.content,
                            timestamp: new Date().toISOString(),
                            isPending: true,
                            media: this.normalizeMediaList(event.media),
                            runId: event.run_id || undefined,
                            runtime,
                        };
                        this.chatHistory.push(this.currentStreamingMessage);
                    } else {
                        this.currentStreamingMessage.content += event.content;
                        if (event.run_id) {
                            this.currentStreamingMessage.runId = event.run_id;
                            this.currentStreamingMessage.runtime = this.ensureRuntime(event.run_id);
                        }
                        if (event.media !== undefined && this.currentStreamingMessage) {
                            this.currentStreamingMessage.media = this.normalizeMediaList(event.media);
                        }
                    }
                    break;

                case 'message': {
                    const normalizedMedia = this.normalizeMediaList(event.media);
                    if (this.currentStreamingMessage) {
                        this.currentStreamingMessage.id = event.id || this.currentStreamingMessage.id;
                        this.currentStreamingMessage.isPending = false;
                        this.currentStreamingMessage.content = event.content;
                        this.currentStreamingMessage.provider = event.provider;
                        this.currentStreamingMessage.runId = event.run_id || this.currentStreamingMessage.runId;
                        if (this.currentStreamingMessage.runId) {
                            this.currentStreamingMessage.runtime = this.ensureRuntime(this.currentStreamingMessage.runId);
                        }
                        if (event.timestamp) {
                            this.currentStreamingMessage.timestamp = event.timestamp;
                        }
                        if (event.media !== undefined) {
                            this.currentStreamingMessage.media = normalizedMedia;
                        }
                        this.currentStreamingMessage = null;
                    } else if (event.role === 'user') {
                        const messageIndex = this.chatHistory.findIndex(m => m.id === event.id);
                        if (messageIndex !== -1) {
                            const existingMessage = this.chatHistory[messageIndex];
                            existingMessage.role = event.role;
                            existingMessage.content = event.content;
                            existingMessage.isPending = false;
                            existingMessage.timestamp = event.timestamp || existingMessage.timestamp || new Date().toISOString();
                            existingMessage.media = normalizedMedia;
                        } else {
                            this.chatHistory.push({
                                id: event.id,
                                role: event.role,
                                content: event.content,
                                timestamp: event.timestamp || new Date().toISOString(),
                                isPending: false,
                                media: normalizedMedia,
                                runId: event.run_id || undefined,
                                runtime: this.ensureRuntime(event.run_id),
                            });
                        }
                    } else {
                        this.chatHistory.push({
                            id: event.id,
                            role: event.role,
                            content: event.content,
                            timestamp: event.timestamp || new Date().toISOString(),
                            isPending: false,
                            media: normalizedMedia,
                            provider: event.provider,
                            runId: event.run_id || undefined,
                            runtime: this.ensureRuntime(event.run_id),
                        });
                    }
                    this.loading = false;
                    break;
                }

                case 'history':
                    const newMessages = event.items.map((m: any) => {
                        const runtime = this.hydrateRuntimeFromHistory(m.runtime_meta);
                        const runId = runtime?.runId;
                        if (runtime && runId) {
                            this.runtimeByRunId.set(runId, runtime);
                        }
                        return {
                            ...m,
                            isPending: false,
                            media: this.normalizeMediaList(m.media),
                            runId: runId || undefined,
                            runtime: runtime || undefined,
                            provider: m.provider || runtime?.model || undefined,
                        };
                    }).sort(
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

                case 'system':
                    if (event.event === 'typing_start') {
                        this.loading = true;
                        if (event.run_id) {
                            this.activeGenerationRunId = event.run_id;
                        }
                    } else if (event.event === 'typing_end') {
                        this.loading = false;
                        this.currentStreamingMessage = null;
                        if (event.run_id && this.activeGenerationRunId === event.run_id) {
                            this.activeGenerationRunId = null;
                        }
                    }
                    break;

                case 'message_end': {
                    if (event.run_id) {
                        const runtime = this.ensureRuntime(event.run_id);
                        if (runtime) {
                            runtime.status = event.stopped ? 'stopped' : 'completed';
                            runtime.finishedAt = event.timestamp || new Date().toISOString();
                            runtime.model = event.model || runtime.model;
                            runtime.usage = event.usage || runtime.usage;
                            runtime.meta = event.meta || runtime.meta;
                            runtime.reasoningElapsedMs = typeof event.reasoning_elapsed_ms === 'number'
                                ? event.reasoning_elapsed_ms
                                : runtime.reasoningElapsedMs;
                            runtime.detailsOpen = false;
                        }
                    }
                    const targetId = event.id || this.currentStreamingMessage?.id;
                    if (targetId) {
                        const messageIndex = this.chatHistory.findIndex(m => m.id === targetId);
                        if (messageIndex !== -1) {
                            const message = this.chatHistory[messageIndex];
                            message.isPending = false;
                            if (event.provider) {
                                message.provider = event.provider;
                            }
                            if (typeof event.reasoning === 'string') {
                                message.reasoning = event.reasoning;
                            }
                            if (event.run_id) {
                                message.runId = event.run_id;
                                message.runtime = this.ensureRuntime(event.run_id);
                            }
                            message.stopped = !!event.stopped;
                            if (!event.stopped && this.ttsEnabled && message.role === 'assistant' && message.id) {
                                this.startPlaybackTracking(message.id, message.content);
                            }
                        }
                    }
                    this.currentStreamingMessage = null;
                    this.loading = false;
                    if (event.run_id && this.activeGenerationRunId === event.run_id) {
                        this.activeGenerationRunId = null;
                    }
                    break;
                }

                case 'error':
                    console.error('[WS] ❌ Error from server:', event.message);
                    this.notificationService.open({
                        type: 'error',
                        message: this.formatWsErrorMessage(event),
                        autoClose: true,
                    });
                    this.loading = false;
                    if (event.run_id) {
                        const runtime = this.ensureRuntime(event.run_id);
                        if (runtime) {
                            runtime.status = 'error';
                            runtime.finishedAt = new Date().toISOString();
                            runtime.detailsOpen = true;
                        }
                    }
                    if (event.run_id && this.activeGenerationRunId === event.run_id) {
                        this.activeGenerationRunId = null;
                    }
                    break;

                case 'ack_message':
                    const idx = this.chatHistory.findIndex(m => m.id === event.tempId);
                    if (idx !== -1) {
                        this.chatHistory[idx].id = event.realId;
                        this.chatHistory[idx].isPending = false;
                        if (event.media) {
                            this.chatHistory[idx].media = this.normalizeMediaList(event.media);
                        }
                    }
                    break;

                case 'runtime_trace':
                    if (event.run_id) {
                        this.pushRuntimeTrace(event.run_id, {
                            stage: event.stage || 'unknown',
                            state: event.state || 'info',
                            timestamp: event.timestamp,
                            elapsedMs: typeof event.elapsed_ms === 'number' ? event.elapsed_ms : undefined,
                            details: event.details || undefined,
                        });
                    }
                    break;

                case 'run_status':
                    if (event.run_id) {
                        this.applyRunStatus(event.run_id, event.status as RuntimeStatus);
                    }
                    if (event.status === 'completed' || event.status === 'stopped' || event.status === 'error' || event.status === 'no_active_run') {
                        this.loading = false;
                        if (event.run_id && this.activeGenerationRunId === event.run_id) {
                            this.activeGenerationRunId = null;
                        }
                    }
                    break;

                default:
                    console.warn('[WS] ⚠️ Unknown event:', event);
            }

            setTimeout(() => this.scrollToBottom(), 50);
        });
    }

    ngOnDestroy(): void {
        this.stopPlaybackTracking();
        this.resetAttachments();
    }

    isMessageStreaming(msg: Message): boolean {
        return msg.isPending === true && msg.role === 'assistant';
    }

    shouldShowActions(msg: Message): boolean {
        if (!msg || msg.isPending) {
            return false;
        }
        if (msg.role === 'assistant') {
            const status = msg.runtime?.status;
            if (status === 'started' || status === 'running' || status === 'stopping') {
                return false;
            }
        }
        return true;
    }

    toggleEmojiDropdown(event: Event): void {
        event.stopPropagation();

        if (!this.showEmojiPicker) {
            if (this.emojiPickerMode === 'dropdown') {
                const target = (event.currentTarget as HTMLElement) || (event.target as HTMLElement);
                if (!target) {
                    return;
                }
                const rect = target.getBoundingClientRect();
                const dropdownWidth = 320;
                const dropdownHeight = 300;

                let x = rect.left;
                if (x + dropdownWidth > window.innerWidth) {
                    x = window.innerWidth - dropdownWidth;
                }
                if (x < 0) {
                    x = 0;
                }

                let y = rect.top - dropdownHeight - 10;
                if (y < 0) {
                    y = rect.bottom + 10;
                }
                if (y + dropdownHeight > window.innerHeight) {
                    y = Math.max(10, window.innerHeight - dropdownHeight - 10);
                }

                this.emojiDropdownPosition = { x, y };
            }

            this.showEmojiPicker = true;
            this.activeDropdown = 'emoji';
        } else {
            this.closeEmojiPicker();
        }
    }

    closeEmojiPicker(): void {
        this.showEmojiPicker = false;
        if (this.activeDropdown === 'emoji') {
            this.activeDropdown = null;
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

        setTimeout(() => {
            const textarea = document.querySelector('.chat-input') as HTMLTextAreaElement;
            if (textarea) {
                textarea.focus();
                this.onKeyUp();
            }
        });
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

    private fetchVoiceModeStatus(): void {
        this.voiceModeLoading = true;
        this.voiceService.voiceModeStatus$()
            .pipe(finalize(() => this.voiceModeLoading = false))
            .subscribe({
                next: (res: VoiceModeResponse) => {
                    if (res && typeof res.running !== 'undefined') {
                        this.voiceModeEnabled = !!res.running;
                    } else {
                        this.fetchVoiceModeStatus();
                    }
                },
                error: (err: any) => {
                    console.error('[VoiceMode] Status error', err);
                },
            });
    }

    toggleVoiceMode(): void {
        if (this.voiceModeLoading) {
            return;
        }

        this.voiceModeLoading = true;
        const request$ = this.voiceModeEnabled
            ? this.voiceService.voiceModeStop$()
            : this.voiceService.voiceModeStart$();

        request$
            .pipe(
                finalize(() => {
                    this.fetchVoiceModeStatus();
                }),
            )
            .subscribe({
                next: (res: VoiceModeResponse) => {
                    this.voiceModeEnabled = !!res?.running;
                },
                error: (err: any) => {
                    console.error('[VoiceMode] Toggle error', err);
                },
            });
    }

    getSettings(): void {
        this.config$ = this.configService.getConfig$().pipe(
            map((config: ProjectConfig | null) => {
                if (!config) {
                    return null;
                }

                const system = config.system || {} as ProjectConfig['system'];
                const userName = system.userName || '';
                const charName = system.charName || '';
                this.ttsEnabled = !!config.voice?.enabled;
                this.userName = userName;
                this.charName = charName;

                return {
                    userName,
                    charName
                };
            })
        )
    }

    // Message handling methods
    sendMessage(): void {
        if (this.loading && this.activeGenerationRunId) {
            return;
        }

        if (!this.websocketService.isConnected()) {
            this.websocketService.reconnect();
            this.notificationService.open({
                type: 'warning',
                message: 'Соединение с сервером восстанавливается. Повторите отправку через секунду.',
                autoClose: true,
            });
            return;
        }

        const trimmed = this.chatInput.value?.trim();
        const mediaPayload = this.attachments.map((attachment) => ({ ...attachment }));
        const hasContent = !!(trimmed && trimmed.length > 0);

        if (!hasContent && mediaPayload.length === 0) {
            return;
        }

        if (this.isProcessingAttachments) {
            this.notificationService.open({
                type: 'warning',
                message: 'Дождитесь завершения обработки вложений перед отправкой.',
                autoClose: true,
            });
            return;
        }

        const tempId = generateTempId();
        const runId = generateTempId();
        const timestamp = new Date().toISOString();

        const userMessage: Message = {
            id: tempId,
            role: 'user',
            content: trimmed ?? '',
            timestamp,
            isPending: true,
            media: mediaPayload,
            runId,
        };

        this.chatHistory.push(userMessage);
        this.chatInputValue = '';
        this.chatInput.setValue('');
        this.resetTextareaHeight();
        this.loading = true;
        this.activeGenerationRunId = runId;
        this.ensureRuntime(runId);
        setTimeout(() => this.scrollToBottom(), 0);

        const transportPayload = {
            ...userMessage,
            run_id: runId,
            actor_user_uuid: this.getActorUserUuid(),
            media: mediaPayload.map((media) => this.serializeMediaForTransport(media)),
        };

        this.websocketService.send(JSON.stringify({
            action: 'send_message',
            payload: transportPayload,
        }));

        this.resetAttachments();
    }

    copyMessage(msg: Message): void {
        navigator.clipboard.writeText(msg.content).then(() => {
            console.log('Copied!');
        });
    }

    stopGeneration(): void {
        if (!this.activeGenerationRunId) {
            return;
        }
        this.websocketService.send(JSON.stringify({
            action: 'stop_generation',
            payload: { run_id: this.activeGenerationRunId },
        }));
        const runtime = this.ensureRuntime(this.activeGenerationRunId);
        if (runtime) {
            runtime.status = 'stopping';
        }
    }

    deleteMessage(msg: Message, chain: boolean): void {
        if (!msg || !msg.id) return;
        this.websocketService.send(JSON.stringify({
            action: 'delete_message',
            payload: { message_id: msg.id, chain }
        }));
    }

    rerollMessage(messageId: string | null): void {
        if (this.loading && this.activeGenerationRunId) {
            this.notificationService.open({
                type: 'warning',
                message: 'Сначала дождитесь завершения текущей генерации или остановите ее.',
                autoClose: true,
            });
            return;
        }

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
        const runId = generateTempId();
        this.activeGenerationRunId = runId;
        this.ensureRuntime(runId);

        const assistantIndex = this.chatHistory.findIndex((msg) => msg.id === messageId);
        let clientUserId: string | null = null;

        if (assistantIndex > 0) {
            for (let i = assistantIndex - 1; i >= 0; i--) {
                const candidate = this.chatHistory[i];
                if (candidate.role === 'user' && candidate.id) {
                    clientUserId = candidate.id;
                    break;
                }
            }
        }

        if (assistantIndex !== -1) {
            this.chatHistory.splice(assistantIndex, 1);
        }

        setTimeout(() => this.scrollToBottom(), 0);

        this.websocketService.send(JSON.stringify({
            action: 'reroll_message',
            payload: {
                message_id: messageId,
                run_id: runId,
                client_user_id: clientUserId,
                actor_user_uuid: this.getActorUserUuid(),
            }
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
            this.voiceService.stopPlay$().subscribe({
                next: () => {
                    this.stopPlaybackTracking();
                },
                error: () => {
                    this.stopPlaybackTracking();
                },
            });
        } else {
            const playRequest = () => {
                this.voiceService.playMessage(msgId).subscribe({
                    next: () => {
                        const msg = this.chatHistory.find((m) => m.id === msgId);
                        this.startPlaybackTracking(msgId, msg?.content);
                    },
                    error: () => {
                        this.stopPlaybackTracking();
                    },
                });
            };

            if (this.currentPlayingMessage) {
                this.voiceService.stopPlay$().subscribe({
                    next: () => playRequest(),
                    error: () => playRequest(),
                });
            } else {
                playRequest();
            }
        }
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
        this.onTextareaInput();
    }

    onTextareaInput(): void {
        const textarea = this.chatTextareaRef?.nativeElement;
        if (!textarea) {
            return;
        }
        const maxHeight = 220;
        textarea.style.height = '0px';
        const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
        textarea.style.height = `${nextHeight}px`;
        textarea.style.overflowY = textarea.scrollHeight > maxHeight ? 'auto' : 'hidden';
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

        const date = this.parseTimestampSafe(isoDate);
        if (!date) {
            return '';
        }
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

    private parseTimestampSafe(raw: string): Date | null {
        const value = String(raw || '').trim();
        if (!value) {
            return null;
        }

        let normalized = value.replace(' ', 'T');
        const hasTimezone = /([zZ]|[+\-]\d{2}:\d{2})$/.test(normalized);
        if (!hasTimezone) {
            // Legacy rows may arrive as naive UTC; force explicit UTC to avoid random offset drift.
            normalized = `${normalized}Z`;
        }

        const parsed = new Date(normalized);
        if (Number.isNaN(parsed.getTime())) {
            return null;
        }
        return parsed;
    }

    // Unused methods - can be removed if not needed
    toggleMessageMenu(msgId: string | null, event: Event): void {
        event.stopPropagation();
        this.activeDropdown = this.activeDropdown === msgId ? null : msgId;
    }

    editMessage(msg: Message): void {
        if (!msg?.id || msg.role !== 'user') {
            return;
        }
        this.editingMessageId = msg.id;
        this.editMessageControl.setValue(msg.content || '');
        setTimeout(() => this.onTextareaInput(), 0);
    }

    isEditingMessage(msg: Message): boolean {
        return !!msg?.id && this.editingMessageId === msg.id;
    }

    isLatestUserMessage(index: number): boolean {
        for (let i = this.chatHistory.length - 1; i >= 0; i--) {
            if (this.chatHistory[i]?.role === 'user') {
                return i === index;
            }
        }
        return false;
    }

    cancelEditMessage(): void {
        this.editingMessageId = null;
        this.editMessageControl.setValue('');
    }

    saveEditMessage(msg: Message): void {
        if (!msg?.id || msg.role !== 'user') {
            return;
        }
        if (this.loading && this.activeGenerationRunId) {
            this.notificationService.open({
                type: 'warning',
                message: 'Сначала дождитесь завершения текущей генерации или остановите ее.',
                autoClose: true,
            });
            return;
        }

        const edited = (this.editMessageControl.value || '').trim();
        if (!edited) {
            this.notificationService.open({
                type: 'warning',
                message: 'Текст сообщения не может быть пустым.',
                autoClose: true,
            });
            return;
        }

        if (edited === (msg.content || '').trim()) {
            this.cancelEditMessage();
            return;
        }

        const runId = generateTempId();
        this.loading = true;
        this.activeGenerationRunId = runId;
        this.ensureRuntime(runId);

        const userIndex = this.chatHistory.findIndex((item) => item.id === msg.id);
        if (userIndex !== -1) {
            this.chatHistory[userIndex].content = edited;
            this.chatHistory[userIndex].isPending = true;
            for (let i = userIndex + 1; i < this.chatHistory.length; i++) {
                if (this.chatHistory[i].role === 'assistant') {
                    this.chatHistory.splice(i, 1);
                    break;
                }
            }
        }

        this.cancelEditMessage();
        setTimeout(() => this.scrollToBottom(), 0);

        this.websocketService.send(JSON.stringify({
            action: 'edit_message',
            payload: {
                message_id: msg.id,
                new_content: edited,
                run_id: runId,
                client_user_id: msg.id,
                actor_user_uuid: this.getActorUserUuid(),
            },
        }));
    }

    toggleAttachDropdown(): void {
        if (this.isProcessingAttachments) {
            return;
        }
        if (this.fileInputRef?.nativeElement) {
            this.fileInputRef.nativeElement.click();
        }
    }

    async onFilesSelected(event: Event): Promise<void> {
        event.stopPropagation();
        const input = event.target as HTMLInputElement;
        const files = Array.from(input?.files ?? []);

        if (!files.length) {
            return;
        }

        this.isProcessingAttachments = true;

        try {
            const processed = await Promise.all(
                files.map((file) =>
                    this.buildMediaFromFile(file).catch((error) => {
                        const message = error instanceof Error ? error.message : String(error);
                        this.notificationService.open({
                            type: 'error',
                            message,
                            autoClose: true,
                        });
                        return null;
                    })
                )
            );

            const validMedia = processed.filter((item): item is MessageMedia => !!item);
            if (validMedia.length) {
                this.attachments = [...this.attachments, ...validMedia];
            }
        } finally {
            this.isProcessingAttachments = false;
            if (this.fileInputRef?.nativeElement) {
                this.fileInputRef.nativeElement.value = '';
            }
        }
    }

    removeAttachment(id: string): void {
        this.attachments = this.attachments.filter((item) => item.id !== id);
    }

    private resetAttachments(): void {
        this.attachments = [];
        this.isProcessingAttachments = false;
        this.selectedMedia = null;
        this.resetTextareaHeight();
        if (this.fileInputRef?.nativeElement) {
            this.fileInputRef.nativeElement.value = '';
        }
    }

    private resetTextareaHeight(): void {
        const textarea = this.chatTextareaRef?.nativeElement;
        if (!textarea) {
            return;
        }
        textarea.style.height = '56px';
        textarea.style.overflowY = 'hidden';
    }

    private serializeMediaForTransport(media: MessageMedia): Omit<MessageMedia, 'dataUrl'> {
        const { dataUrl, ...rest } = media;
        return rest;
    }

    private async buildMediaFromFile(file: File): Promise<MessageMedia> {
        if (!file) {
            throw new Error('Файл не найден.');
        }

        const mimeType = file.type || DEFAULT_MIME_TYPE;
        const category = this.determineMediaCategory(mimeType, file.name);
        const dataUrl = await this.readFileAsDataUrl(file);
        const base64 = dataUrl.split(',')[1];

        if (!base64) {
            throw new Error(`Не удалось прочитать файл ${file.name}.`);
        }

        return {
            id: generateTempId(),
            name: file.name,
            mimeType,
            size: file.size,
            category,
            data: base64,
            dataUrl,
        };
    }

    private readFileAsDataUrl(file: File): Promise<string> {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result as string);
            reader.onerror = () => reject(new Error(`Ошибка чтения файла ${file.name}.`));
            reader.readAsDataURL(file);
        });
    }

    private determineMediaCategory(mimeType: string, fileName: string): MessageMediaCategory {
        if (mimeType?.startsWith('image/')) {
            return 'image';
        }
        if (mimeType?.startsWith('audio/')) {
            return 'audio';
        }
        if (mimeType?.startsWith('video/')) {
            return 'video';
        }

        const extension = fileName?.split('.').pop()?.toLowerCase();
        if (extension && DOCUMENT_EXTENSIONS.has(extension)) {
            return 'document';
        }

        return 'other';
    }

    private normalizeMediaList(media?: any[]): MessageMedia[] {
        if (!Array.isArray(media)) {
            return [];
        }

        return media.map((item: any) => {
            const mimeType = item.mimeType || item.type || DEFAULT_MIME_TYPE;
            const name = item.name || item.originalName || 'file';
            const category: MessageMediaCategory = item.category || this.determineMediaCategory(mimeType, name);
            const data: string | undefined = item.data || undefined;
            const dataUrl: string | undefined = item.dataUrl || (data ? 'data:' + mimeType + ';base64,' + data : undefined);

            return {
                id: item.id || generateTempId(),
                name,
                mimeType,
                size: item.size ?? 0,
                category,
                description: item.description || undefined,
                url: item.url || undefined,
                data,
                dataUrl,
            } as MessageMedia;
        });
    }

    private getActorUserUuid(): string | undefined {
        return this.authService.getCurrentUser()?.uuid;
    }

    getMediaSource(media: MessageMedia | null | undefined): string {
        if (!media) {
            return '';
        }
        if (media.dataUrl) {
            return media.dataUrl;
        }
        if (media.data) {
            return `data:${media.mimeType};base64,${media.data}`;
        }
        return media.url ?? '';
    }

    previewMedia(media: MessageMedia): void {
        if (media.category === 'image') {
            this.selectedMedia = media;
            return;
        }

        if (media.category === 'document' || media.category === 'other') {
            this.downloadMedia(media);
        }
    }

    closeMediaPreview(): void {
        this.selectedMedia = null;
    }

    downloadMedia(media: MessageMedia): void {
        const source = this.getMediaSource(media);
        if (!source) {
            this.notificationService.open({
                type: 'warning',
                message: 'Не удалось загрузить файл.',
                autoClose: true,
            });
            return;
        }

        const link = document.createElement('a');
        link.href = source;
        link.download = media.name;
        link.target = '_blank';
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    shouldShowReroll(msg: Message, index: number): boolean {
        return msg.role === 'assistant' && index === this.chatHistory.length - 1;
    }

    hasRuntime(msg: Message): boolean {
        return !!msg.runtime && (msg.runtime.traces.length > 0 || !!msg.runtime.usage || !!msg.provider);
    }

    hasUsageMeta(msg: Message): boolean {
        const hasUsage = !!msg.runtime?.usage && Object.keys(msg.runtime.usage || {}).length > 0;
        const hasMeta = !!msg.runtime?.meta && Object.keys(msg.runtime.meta || {}).length > 0;
        return hasUsage || hasMeta;
    }

    toggleRuntimeDetails(msg: Message): void {
        if (!msg.runtime) {
            return;
        }
        msg.runtime.detailsOpen = !msg.runtime.detailsOpen;
    }

    getRuntimeSummary(msg: Message): string {
        const runtime = msg.runtime;
        if (!runtime) {
            return '';
        }
        const status = runtime.status === 'completed'
            ? 'готово'
            : runtime.status === 'stopped'
                ? 'остановлено'
                : runtime.status === 'error'
                    ? 'ошибка'
                    : runtime.status === 'stopping'
                        ? 'останавливаю...'
                        : 'в процессе';
        const model = runtime.model || msg.provider || 'provider';
        if (typeof runtime.elapsedMs === 'number') {
            const seconds = Math.max(0, Math.round(runtime.elapsedMs / 10) / 100);
            return `${model} • ${status} • ${seconds}s`;
        }
        return `${model} • ${status}`;
    }

    getRuntimeStages(msg: Message): RuntimeStageView[] {
        const runtime = msg.runtime;
        if (!runtime) {
            return [];
        }
        return this.getRuntimeStagesFromRuntime(runtime);
    }

    private getRuntimeStagesFromRuntime(runtime: RuntimeState): RuntimeStageView[] {
        const traces = runtime.traces || [];

        return RUNTIME_STAGE_GROUPS
            .map((group) => {
                const related = traces.filter((trace) => group.keys.includes(trace.stage));
                const hasStart = related.some((trace) => trace.state === 'start');
                const hasEnd = related.some((trace) => trace.state === 'end');
                const endTrace = related.find((trace) => trace.state === 'end' && typeof trace.elapsedMs === 'number');
                const state: RuntimeStageView['state'] = hasEnd ? 'done' : (hasStart ? 'active' : 'pending');
                const elapsedMs = endTrace?.elapsedMs;
                return {
                    id: group.id,
                    label: group.label,
                    state,
                    elapsedMs,
                };
            })
            .filter((stage) => {
                const meta = RUNTIME_STAGE_GROUPS.find((group) => group.id === stage.id);
                if (!meta?.optional) {
                    return true;
                }
                return stage.state !== 'pending';
            });
    }

    getRuntimeActiveLabel(msg: Message): string {
        const runtime = msg.runtime;
        if (!runtime) {
            return 'Обрабатываю запрос';
        }
        return this.getRuntimeActiveLabelFromRuntime(runtime);
    }

    getActiveRuntime(): RuntimeState | undefined {
        if (!this.activeGenerationRunId) {
            return undefined;
        }
        return this.runtimeByRunId.get(this.activeGenerationRunId);
    }

    getActiveRuntimeLabel(): string {
        const runtime = this.getActiveRuntime();
        if (!runtime) {
            return 'Обрабатываю запрос';
        }
        return this.getRuntimeActiveLabelFromRuntime(runtime);
    }

    private getRuntimeActiveLabelFromRuntime(runtime: RuntimeState): string {
        const stages = this.getRuntimeStagesFromRuntime(runtime);
        const active = stages.find((stage) => stage.state === 'active');
        if (active) {
            return active.label;
        }
        if (runtime.status === 'completed') {
            return 'Ответ готов';
        }
        if (runtime.status === 'stopped') {
            return 'Генерация остановлена';
        }
        if (runtime.status === 'error') {
            return 'Ошибка генерации';
        }
        return 'Обрабатываю запрос';
    }

    trackByMessage(_index: number, msg: Message): string {
        return msg.id;
    }

    trackByMedia(_index: number, media: MessageMedia): string {
        return media.id;
    }

    trackByAttachment(_index: number, attachment: MessageMedia): string {
        return attachment.id;
    }

    getUsageTooltip(msg: Message): string {
        const usage = msg.runtime?.usage || {};
        const meta = msg.runtime?.meta || {};
        const reasoningElapsedMs = msg.runtime?.reasoningElapsedMs;
        if (!Object.keys(usage).length && !Object.keys(meta).length && typeof reasoningElapsedMs !== 'number') {
            return '';
        }
        const keys = [
            'prompt_eval_count',
            'eval_count',
            'total_duration',
            'eval_duration',
            'prompt_eval_duration',
        ];
        const lines: string[] = [];
        for (const key of keys) {
            if (usage[key] !== undefined && usage[key] !== null) {
                lines.push(`${key}: ${usage[key]}`);
            }
        }
        for (const [key, value] of Object.entries(usage)) {
            if (!keys.includes(key) && value !== undefined && value !== null) {
                lines.push(`${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`);
            }
        }
        if (typeof reasoningElapsedMs === 'number') {
            const secs = Math.max(0, Math.round(reasoningElapsedMs / 10) / 100);
            lines.push(`reasoning_elapsed: ${secs}s`);
        }
        for (const [key, value] of Object.entries(meta)) {
            if (value !== undefined && value !== null) {
                lines.push(`meta.${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`);
            }
        }
        return lines.join('\n');
    }

    private formatWsErrorMessage(event: any): string {
        const fallback = event?.message || 'Ошибка во время генерации.';
        const details = event?.details;
        if (!Array.isArray(details) || details.length === 0) {
            return fallback;
        }

        const normalized = details
            .map((item: any) => {
                const provider = item?.provider ? String(item.provider) : 'provider';
                const reason = item?.reason ? String(item.reason) : '';
                return reason ? `${provider}: ${reason}` : provider;
            })
            .filter(Boolean);

        if (!normalized.length) {
            return fallback;
        }

        return `Провайдер отказал: ${normalized.join(' | ')}`;
    }

    getThinkingDurationMs(msg: Message): number | undefined {
        return msg.runtime?.reasoningElapsedMs;
    }

    private ensureRuntime(runId?: string | null): RuntimeState | undefined {
        if (!runId) {
            return undefined;
        }
        const existing = this.runtimeByRunId.get(runId);
        if (existing) {
            return existing;
        }
        const runtime: RuntimeState = {
            runId,
            status: 'running',
            startedAt: new Date().toISOString(),
            detailsOpen: false,
            traces: [],
            usage: null,
            meta: null,
        };
        this.runtimeByRunId.set(runId, runtime);
        return runtime;
    }

    private pushRuntimeTrace(runId: string, trace: RuntimeTraceEntry): void {
        const runtime = this.ensureRuntime(runId);
        if (!runtime) {
            return;
        }
        runtime.traces = [...runtime.traces, trace];
        if (trace.state === 'end' && typeof trace.elapsedMs === 'number' && trace.stage === 'pipeline') {
            runtime.elapsedMs = trace.elapsedMs;
        }
        if (trace.state === 'start' && trace.stage === 'pipeline' && !runtime.startedAt) {
            runtime.startedAt = trace.timestamp || new Date().toISOString();
        }
        const linkedMessage = this.chatHistory.find((msg) => msg.runId === runId && msg.role === 'assistant');
        if (linkedMessage) {
            linkedMessage.runtime = runtime;
        }
    }

    private applyRunStatus(runId: string, status: RuntimeStatus): void {
        const runtime = this.ensureRuntime(runId);
        if (!runtime) {
            return;
        }
        runtime.status = status;
        if (status === 'completed' || status === 'stopped' || status === 'error') {
            runtime.finishedAt = new Date().toISOString();
            if (typeof runtime.elapsedMs !== 'number') {
                runtime.elapsedMs = this.estimateElapsedMs(runtime);
            }
        }
        const linkedMessage = this.chatHistory.find((msg) => msg.runId === runId && msg.role === 'assistant');
        if (linkedMessage) {
            linkedMessage.runtime = runtime;
        }
    }

    private estimateElapsedMs(runtime: RuntimeState): number {
        const started = runtime.startedAt ? new Date(runtime.startedAt).getTime() : Date.now();
        const finished = runtime.finishedAt ? new Date(runtime.finishedAt).getTime() : Date.now();
        return Math.max(0, finished - started);
    }

    private startPlaybackTracking(messageId: string, text?: string): void {
        this.currentPlayingMessage = messageId;

        if (this.playbackResetTimer) {
            clearTimeout(this.playbackResetTimer);
            this.playbackResetTimer = null;
        }

        const timeoutMs = this.estimatePlaybackDurationMs(text);
        this.playbackResetTimer = setTimeout(() => {
            if (this.currentPlayingMessage === messageId) {
                this.currentPlayingMessage = null;
            }
            this.playbackResetTimer = null;
        }, timeoutMs);
    }

    private stopPlaybackTracking(): void {
        this.currentPlayingMessage = null;
        if (this.playbackResetTimer) {
            clearTimeout(this.playbackResetTimer);
            this.playbackResetTimer = null;
        }
    }

    private estimatePlaybackDurationMs(text?: string): number {
        const chars = (text || '').length;
        if (chars <= 0) {
            return 5000;
        }
        const charsPerSecond = 14; // conservative RU/EN TTS pace
        const estimatedMs = Math.round((chars / charsPerSecond) * 1000) + 1200;
        return Math.min(Math.max(estimatedMs, 3000), 120000);
    }

    private hydrateRuntimeFromHistory(raw: any): RuntimeState | undefined {
        if (!raw || typeof raw !== 'object') {
            return undefined;
        }
        const tracesRaw = Array.isArray(raw.traces) ? raw.traces : [];
        const traces: RuntimeTraceEntry[] = tracesRaw.map((trace: any) => ({
            stage: trace?.stage || 'unknown',
            state: trace?.state || 'info',
            timestamp: trace?.timestamp,
            elapsedMs: typeof trace?.elapsed_ms === 'number'
                ? trace.elapsed_ms
                : (typeof trace?.elapsedMs === 'number' ? trace.elapsedMs : undefined),
            details: trace?.details,
        }));
        const runId = raw.run_id || raw.runId;
        if (!runId) {
            return undefined;
        }
        const status: RuntimeStatus = raw.stopped ? 'stopped' : 'completed';
        return {
            runId,
            status,
            startedAt: raw.started_at || raw.startedAt || undefined,
            finishedAt: raw.timestamp || raw.finishedAt || undefined,
            elapsedMs: typeof raw.elapsed_ms === 'number' ? raw.elapsed_ms : (typeof raw.elapsedMs === 'number' ? raw.elapsedMs : undefined),
            model: raw.model || undefined,
            usage: raw.usage || null,
            meta: raw.meta || null,
            reasoningElapsedMs: typeof raw.reasoning_elapsed_ms === 'number'
                ? raw.reasoning_elapsed_ms
                : (typeof raw.reasoningElapsedMs === 'number' ? raw.reasoningElapsedMs : undefined),
            detailsOpen: false,
            traces,
        };
    }
}
