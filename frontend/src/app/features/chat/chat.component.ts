import { AfterViewInit, Component, DestroyRef, ElementRef, HostListener, OnDestroy, OnInit, ViewChild, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { UntypedFormControl } from '@angular/forms';
import { Observable } from 'rxjs';
import { finalize, map } from 'rxjs/operators';
import { LibraryItem } from '../../core/models/library.model';
import { Message, MessageCompliance, MessageMedia, MessageMediaCategory } from '../../core/models/message.model';
import { ProjectConfig } from '../../core/models/project-config.model';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { ConfigService } from '../../core/services/config.service';
import { LibraryService } from '../../core/services/library.service';
import { VoiceModeResponse, VoiceService } from '../../core/services/voice.service';
import { BufferedWebsocketMessage, WebsocketService } from '../../core/services/websocket.service';
import { NotificationService } from '../../shared/components/notification/notification.service';
import { ChatComposerComponent, ComposerContextAttachment } from './components/chat-composer/chat-composer.component';
import {
    ChatMessageStoreService,
    ChatRunStoreService,
    ChatWsEvent,
    RuntimeStageView,
    RuntimeState,
    RuntimeStatus,
    RuntimeTraceEntry,
    UsageDetailLine,
    getRuntimeActiveLabel,
    getRuntimeStages,
    getRuntimeSummary,
    getUsageDetailLines,
} from './store';
import { isNearScrollBottom } from './utils/chat-scroll.util';
import {
    getStreamingRenderContent,
    hasClosedThinkingBlock,
    hasOpenThinkingBlock,
    shouldCollapseThinkingBlock,
} from './utils/chat-thinking.util';

function generateTempId(): string {
    if ((crypto as any).randomUUID) {
        return (crypto as any).randomUUID();
    }
    return 'temp-' + Math.random().toString(36).substr(2, 9);
}

const DEFAULT_MIME_TYPE = 'application/octet-stream';
const DOCUMENT_EXTENSIONS = new Set(['pdf', 'doc', 'docx', 'txt', 'rtf', 'xls', 'xlsx', 'csv', 'ppt', 'pptx']);
const LONG_USER_MESSAGE_THRESHOLD = 1000;
const COLLAPSED_USER_MESSAGE_LENGTH = 900;

interface ChatMessageViewModel {
    msg: Message;
    index: number;
    formattedTimestamp: string;
    messageSource?: Message['source'];
    isLatestUserMessage: boolean;
    isLatestAssistantMessage: boolean;
    canContinue: boolean;
    hasRuntime: boolean;
    runtimeSummary: string;
    runtimeActiveLabel: string;
    runtimeStages: RuntimeStageView[];
    renderContent: string;
    isStreaming: boolean;
    thinkingDurationMs?: number;
    collapseThinking: boolean;
    userContentExpandable: boolean;
    userContentExpanded: boolean;
    hasUsageMeta: boolean;
    usageLines: UsageDetailLine[];
}

interface CachedChatMessageView {
    messageRef: Message;
    index: number;
    total: number;
    latestUserIndex: number;
    showAllSources: boolean;
    userContentExpanded: boolean;
    view: ChatMessageViewModel;
}

@Component({
    selector: 'app-chat',
    templateUrl: './chat.component.html',
    styleUrls: ['./chat.component.less']
})
export class ChatComponent implements OnInit, AfterViewInit, OnDestroy {
    private static readonly CHAT_ALL_SOURCES_KEY = 'chat.showAllSources';
    private readonly destroyRef = inject(DestroyRef);

    @HostListener('document:click', ['$event'])
    onClickOutside(): void {
        this.activeDropdown = null;
        this.showEmojiPicker = false;
        this.activeUsageMessageId = null;
    }

    private handleMessageChunk(event: any): void {
        if (event.run_id) {
            this.activeGenerationRunId = event.run_id;
            this.chatRunStore.setActiveRunId(event.run_id);
        }
        let current = this.chatMessageStore.currentStreamingMessage;
        if (!current) {
            this.loading = false;
            const tempId = event.id || generateTempId();
            const runtime = this.ensureRuntime(event.run_id);
            current = this.chatMessageStore.startStreaming({
                id: tempId,
                role: event.role,
                content: '',
                timestamp: new Date().toISOString(),
                isPending: true,
                media: this.normalizeMediaList(event.media),
                source: this.normalizeSource(event.source),
                runId: event.run_id || undefined,
                runtime,
            });
        } else {
            const patch: Partial<Message> = {};
            if (event.run_id) {
                patch.runId = event.run_id;
                patch.runtime = this.ensureRuntime(event.run_id);
            }
            if (event.media !== undefined) {
                patch.media = this.normalizeMediaList(event.media);
            }
            if (Object.keys(patch).length) {
                current = this.chatMessageStore.patchStreaming(patch) || current;
            }
        }

        if (event.content) {
            this.chatMessageStore.appendStreamingContent(String(event.content));
        }
    }

    @HostListener('window:chat-history-source-filter-changed', ['$event'])
    onSourceFilterChanged(event: CustomEvent<{ showAllSources?: boolean }>): void {
        this.showAllChatSources = !!event.detail?.showAllSources;
        this.chatMessageViewCache.clear();
        this.rebuildChatMessageViews(this.chatHistory);
        this.loadHistory();
    }

    @HostListener('window:resize')
    onWindowResize(): void {
        this.syncChatScrollbarCompensation();
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
    readonly chatMessageViews = signal<ChatMessageViewModel[]>([]);
    historyLoaded = false;
    loading = false;
    chatInputValue: string = '';
    userName: string = '';
    charName: string = '';
    attachments: MessageMedia[] = [];
    contextAttachments: ComposerContextAttachment[] = [];
    imageGenerationEnabled = false;
    codeInterpreterEnabled = false;
    webpageModalOpen = false;
    webpageUrlControl = new UntypedFormControl('');
    webpageProcessingMode: 'extract' | 'link' = 'extract';
    webpageUrlError = '';
    largeMessagePromptOpen = false;
    private pendingLargeMessageText: string | null = null;
    private skipLargeMessagePromptOnce = false;
    selectedMedia: MessageMedia | null = null;
    isProcessingAttachments = false;
    showAllChatSources = false;
    libraryPickerOpen = false;
    libraryPickerLoading = false;
    libraryPickerQuery = '';
    libraryItems: LibraryItem[] = [];

    config$: Observable<{ userName: string; charName: string } | null> | null = null;

    recording = false;
    voiceModeEnabled = false;
    voiceModeLoading = false;
    activeDropdown: string | null = null;
    currentPlayingMessage: string | null = null;
    activeGenerationRunId: string | null = null;
    refreshHistoryAfterRunId: string | null = null;
    ttsEnabled = false;
    isComposerScrollable = false;
    editingMessageId: string | null = null;
    editMessageControl = new UntypedFormControl('');
    private pendingRealtimeScroll = false;
    private shouldAutoScrollOnMessageFlush = false;
    private pendingHistoryPrependScroll: { scrollHeight: number; scrollTop: number } | null = null;
    private playbackResetTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly chatMessageViewCache = new Map<string, CachedChatMessageView>();
    private readonly expandedUserMessageIds = new Set<string>();
    activeUsageMessageId: string | null = null;
    @ViewChild('messagesContainer') private messagesContainerRef?: ElementRef<HTMLElement>;
    @ViewChild(ChatComposerComponent) private composerRef?: ChatComposerComponent;

    constructor(
        private apiService: ApiService,
        private authService: AuthService,
        private configService: ConfigService,
        private libraryService: LibraryService,
        private voiceService: VoiceService,
        private websocketService: WebsocketService,
        private notificationService: NotificationService,
        private chatRunStore: ChatRunStoreService,
        private chatMessageStore: ChatMessageStoreService
    ) { }

    ngOnInit(): void {
        if ('scrollRestoration' in history) {
            history.scrollRestoration = 'manual';
        }
        this.showAllChatSources = this.readShowAllChatSources();
        this.getSettings();
        if (this.chatMessageStore.messages.length) {
            this.chatHistory = this.chatMessageStore.messages;
            this.rebuildChatMessageViews(this.chatHistory);
            this.historyLoaded = true;
            this.currentOffset = this.chatHistory.length;
        } else {
            this.loadHistory();
        }
        this.fetchVoiceModeStatus();
        this.chatMessageStore.messages$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((messages) => {
                this.chatHistory = messages;
                this.rebuildChatMessageViews(messages);
                if (this.shouldAutoScrollOnMessageFlush) {
                    this.scheduleScrollToBottom();
                }
            });

        const handleBufferedWebsocketMessage = (wsEvent: BufferedWebsocketMessage): void => {
            if (!this.claimBufferedWebsocketMessage(wsEvent)) {
                return;
            }
            const rawMsg = wsEvent.data;
            let event: ChatWsEvent;
            try {
                event = JSON.parse(rawMsg);
            } catch {
                console.warn('[WS] ⚠️ Received non-JSON message:', rawMsg);
                this.isLoadingHistory = false;
                return;
            }

            const shouldStickToBottom = this.shouldStickToBottom();
            let shouldScrollAfterEvent = false;

            switch (event.type) {
                case 'message_chunk':
                    this.shouldAutoScrollOnMessageFlush = shouldStickToBottom;
                    this.handleMessageChunk(event);
                    break;

                case 'message': {
                    const normalizedMedia = this.normalizeMediaList(event.media);
                    const currentStreamingMessage = this.chatMessageStore.currentStreamingMessage;
                    if (currentStreamingMessage) {
                        const runId = event.run_id || currentStreamingMessage.runId;
                        const finalPatch: Partial<Message> = {
                            isPending: false,
                            content: event.content,
                            provider: event.provider,
                            runId,
                            runtime: runId ? this.ensureRuntime(runId) : currentStreamingMessage.runtime,
                            timestamp: event.timestamp || currentStreamingMessage.timestamp,
                            media: event.media !== undefined ? normalizedMedia : currentStreamingMessage.media,
                            source: this.normalizeSource(event.source) || currentStreamingMessage.source,
                            parent_message_id: event.parent_message_id ?? currentStreamingMessage.parent_message_id,
                            variant_group_id: event.variant_group_id ?? currentStreamingMessage.variant_group_id,
                            variant_index: event.variant_index ?? currentStreamingMessage.variant_index,
                            active_variant: event.active_variant ?? currentStreamingMessage.active_variant,
                            variants: event.variants ?? currentStreamingMessage.variants,
                        };
                        if (event.id && event.id !== currentStreamingMessage.id) {
                            this.chatMessageStore.replaceTempId(currentStreamingMessage.id, event.id, {
                                ...finalPatch,
                            });
                        } else {
                            this.chatMessageStore.patchStreaming(finalPatch);
                        }
                        this.chatMessageStore.finishStreaming();
                    } else if (event.role === 'user') {
                        const messageIndex = this.chatHistory.findIndex(m => m.id === event.id);
                        if (messageIndex !== -1) {
                            const existingMessage = this.chatHistory[messageIndex];
                            this.chatMessageStore.patchById(existingMessage.id, {
                                role: event.role,
                                content: event.content,
                                isPending: false,
                                timestamp: event.timestamp || existingMessage.timestamp || new Date().toISOString(),
                                media: normalizedMedia,
                                source: this.normalizeSource(event.source) || existingMessage.source,
                            });
                        } else {
                            this.chatMessageStore.push({
                                id: event.id,
                                role: event.role,
                                content: event.content,
                                timestamp: event.timestamp || new Date().toISOString(),
                                isPending: false,
                                media: normalizedMedia,
                                source: this.normalizeSource(event.source),
                                runId: event.run_id || undefined,
                                runtime: this.ensureRuntime(event.run_id),
                                parent_message_id: event.parent_message_id,
                                variant_group_id: event.variant_group_id,
                                variant_index: event.variant_index,
                                active_variant: event.active_variant,
                                variants: event.variants,
                            });
                        }
                    } else {
                        this.chatMessageStore.push({
                            id: event.id,
                            role: event.role,
                            content: event.content,
                            timestamp: event.timestamp || new Date().toISOString(),
                            isPending: false,
                            media: normalizedMedia,
                            source: this.normalizeSource(event.source),
                            provider: event.provider,
                            runId: event.run_id || undefined,
                            runtime: this.ensureRuntime(event.run_id),
                            parent_message_id: event.parent_message_id,
                            variant_group_id: event.variant_group_id,
                            variant_index: event.variant_index,
                            active_variant: event.active_variant,
                            variants: event.variants,
                        });
                    }
                    this.loading = false;
                    shouldScrollAfterEvent = shouldStickToBottom;
                    break;
                }

                case 'message_variant_activated': {
                    this.applyActivatedMessageVariant(event);
                    shouldScrollAfterEvent = false;
                    break;
                }

                case 'compliance_update': {
                    // Post-stream compliance results (§3.5/3.5-bis/3.8/3.9)
                    // for the just-finished assistant message.
                    const compliance = this.normalizeComplianceEvent(event.compliance);
                    if (event.id && compliance) {
                        this.chatMessageStore.patchById(event.id, { compliance });
                    }
                    shouldScrollAfterEvent = false;
                    break;
                }

                case 'history':
                    const newMessages = (event.items || []).filter((m: any) => {
                        const role = String(m?.role || '').toLowerCase();
                        return role !== 'tool';
                    }).map((m: any) => {
                        const runtime = this.hydrateRuntimeFromHistory(m.runtime_meta);
                        const runId = runtime?.runId;
                        if (runtime && runId) {
                            this.chatRunStore.setRuntime(runId, runtime);
                        }
                        return {
                            ...m,
                            isPending: false,
                            media: this.normalizeMediaList(m.media),
                            source: this.normalizeSource(m.source),
                            runId: runId || undefined,
                            runtime: runtime || undefined,
                            provider: m.provider || runtime?.model || undefined,
                            compliance: this.extractComplianceFromMeta(m.runtime_meta),
                        };
                    }).sort(
                        (a: any, b: any) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
                    );

                    if (this.isLoadingHistory) {
                        // Append older messages to the beginning
                        this.currentOffset += newMessages.length;
                        this.hasMoreMessages = newMessages.length === this.MESSAGES_PER_PAGE;
                        this.isLoadingHistory = false;
                        this.chatMessageStore.prependHistory(newMessages);
                        this.restoreScrollAfterHistoryPrepend();
                    } else {
                        // Initial load
                        this.chatMessageStore.setHistory(newMessages);
                        this.currentOffset = newMessages.length;
                        this.hasMoreMessages = newMessages.length === this.MESSAGES_PER_PAGE;
                        this.historyLoaded = true;
                        shouldScrollAfterEvent = true;
                        this.scheduleInitialHistoryScrollToBottom();
                    }
                    break;

                case 'deleted':
                    this.chatMessageStore.deleteMessage(event.message_id, !!event.chain);
                    break;

                case 'system':
                    if (event.event === 'typing_start') {
                        this.loading = true;
                        if (event.run_id) {
                            this.activeGenerationRunId = event.run_id;
                            this.chatRunStore.setActiveRunId(event.run_id);
                        }
                    } else if (event.event === 'thinking_start' || event.event === 'answer_start') {
                        this.loading = true;
                        if (event.run_id) {
                            this.activeGenerationRunId = event.run_id;
                            this.chatRunStore.setActiveRunId(event.run_id);
                        }
                    } else if (event.event === 'skip_thinking_requested') {
                        this.notificationService.open({
                            type: 'info',
                            message: event.message || 'Пропускаю размышление.',
                            autoClose: true,
                        });
                    } else if (event.event === 'skip_thinking_failed') {
                        this.notificationService.open({
                            type: 'warning',
                            message: event.message || 'Пропуск размышления не удался.',
                            autoClose: true,
                        });
                    } else if (event.event === 'typing_end') {
                        this.loading = false;
                        this.chatMessageStore.finishStreaming();
                        if (event.run_id && this.activeGenerationRunId === event.run_id) {
                            this.activeGenerationRunId = null;
                            this.chatRunStore.setActiveRunId(null);
                        }
                    }
                    shouldScrollAfterEvent = shouldStickToBottom;
                    break;

                case 'message_end': {
                    let finalRuntime: RuntimeState | undefined;
                    if (event.run_id) {
                        finalRuntime = this.chatRunStore.patchMessageEnd(event.run_id, event);
                    }
                    const message = this.findMessageForRunEnd(event);
                    if (message) {
                        const patch: Partial<Message> = { isPending: false, stopped: !!event.stopped };
                        if (event.provider) {
                            patch.provider = event.provider;
                        }
                        if (typeof event.reasoning === 'string') {
                            patch.reasoning = event.reasoning;
                        }
                        if (event.run_id) {
                            patch.runId = event.run_id;
                            patch.runtime = finalRuntime || this.ensureRuntime(event.run_id);
                        }
                        this.chatMessageStore.patchById(message.id, patch);
                        if (!event.stopped && event.voice_playback_started === true && message.role === 'assistant' && message.id) {
                            this.startPlaybackTracking(message.id, message.content);
                        }
                    }
                    this.chatMessageStore.finishStreaming();
                    this.loading = false;
                    if (event.run_id && this.activeGenerationRunId === event.run_id) {
                        this.activeGenerationRunId = null;
                        this.chatRunStore.setActiveRunId(null);
                    }
                    shouldScrollAfterEvent = shouldStickToBottom;
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
                            this.chatMessageStore.linkRuntime(event.run_id, runtime);
                        }
                    }
                    if (event.run_id && this.activeGenerationRunId === event.run_id) {
                        this.activeGenerationRunId = null;
                        this.chatRunStore.setActiveRunId(null);
                    }
                    shouldScrollAfterEvent = shouldStickToBottom;
                    break;

                case 'ack_message':
                    const idx = this.chatHistory.findIndex(m => m.id === event.tempId);
                    if (idx !== -1) {
                        this.chatMessageStore.replaceTempId(event.tempId, event.realId, {
                            isPending: false,
                            media: event.media ? this.normalizeMediaList(event.media) : this.chatHistory[idx].media,
                        });
                    }
                    shouldScrollAfterEvent = shouldStickToBottom;
                    break;

                case 'runtime_trace':
                    if (event.run_id) {
                        this.pushRuntimeTrace(event.run_id, this.normalizeRuntimeTrace(event));
                    }
                    shouldScrollAfterEvent = shouldStickToBottom;
                    break;

                case 'run_status':
                    if (event.run_id) {
                        this.applyRunStatus(event.run_id, event.status as RuntimeStatus);
                    }
                    if (event.status === 'completed' || event.status === 'stopped' || event.status === 'error' || event.status === 'no_active_run') {
                        this.loading = false;
                        if (event.run_id && this.activeGenerationRunId === event.run_id) {
                            this.activeGenerationRunId = null;
                            this.chatRunStore.setActiveRunId(null);
                        }
                        if (event.run_id && this.refreshHistoryAfterRunId === event.run_id && event.status === 'completed') {
                            this.refreshHistoryAfterRunId = null;
                            this.loadHistory();
                        }
                    }
                    shouldScrollAfterEvent = shouldStickToBottom;
                    break;

                default:
                    console.warn('[WS] ⚠️ Unknown event:', event);
            }

            if (shouldScrollAfterEvent) {
                this.scheduleScrollToBottom();
            }
        };

        this.websocketService
            .getBufferedMessagesAfter(this.websocketService.getConsumerCursor('chat'))
            .forEach(handleBufferedWebsocketMessage);
        this.websocketService.bufferedMessages$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe(handleBufferedWebsocketMessage);
    }

    ngAfterViewInit(): void {
        requestAnimationFrame(() => {
            this.composerRef?.resizeTextarea();
            this.syncChatScrollbarCompensation();
            if (this.historyLoaded) {
                this.scheduleInitialHistoryScrollToBottom();
            }
        });
    }

    ngOnDestroy(): void {
        this.stopPlaybackTracking();
        this.resetAttachments();
    }

    private claimBufferedWebsocketMessage(event: BufferedWebsocketMessage): boolean {
        const cursor = this.websocketService.getConsumerCursor('chat');
        if (event.sequence <= cursor) {
            return false;
        }
        this.websocketService.setConsumerCursor('chat', event.sequence);
        return true;
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

        const element = this.messagesContainerRef?.nativeElement;
        this.pendingHistoryPrependScroll = element
            ? { scrollHeight: element.scrollHeight, scrollTop: element.scrollTop }
            : null;
        this.isLoadingHistory = true;

        this.websocketService.send(JSON.stringify({
            action: 'fetch_history',
            payload: {
                limit: this.MESSAGES_PER_PAGE,
                offset: this.currentOffset, // Правильный offset - не увеличиваем лимит, а сдвигаем позицию
                include_all_sources: this.showAllChatSources,
                actor_user_uuid: this.getActorUserUuid(),
            }
        }));
    }

    addEmoji(emoji: string): void {
        const currentValue = this.chatInput.value || '';
        const newValue = currentValue + emoji;
        this.chatInput.setValue(newValue);

        setTimeout(() => {
            this.composerRef?.focusInput();
            this.composerRef?.resizeTextarea();
        });
    }

    loadHistory(): void {
        this.currentOffset = 0;
        this.hasMoreMessages = true;
        this.isLoadingHistory = false;
        this.historyLoaded = false;

        this.websocketService.send(JSON.stringify({
            action: 'fetch_history',
            payload: {
                limit: this.MESSAGES_PER_PAGE,
                include_all_sources: this.showAllChatSources,
                actor_user_uuid: this.getActorUserUuid(),
            }
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
    async sendMessage(): Promise<void> {
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

        let trimmed = this.chatInput.value?.trim();
        let mediaPayload = this.attachments.map((attachment) => ({ ...attachment }));
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

        if (
            !this.skipLargeMessagePromptOnce
            && trimmed
            && trimmed.length > LONG_USER_MESSAGE_THRESHOLD
        ) {
            this.pendingLargeMessageText = trimmed;
            this.largeMessagePromptOpen = true;
            return;
        }

        this.skipLargeMessagePromptOnce = false;

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
            source: { name: 'main_chat', label: 'Main chat' },
            runId,
        };

        this.chatMessageStore.push(userMessage);
        this.chatInputValue = '';
        this.chatInput.setValue('');
        this.resetTextareaHeight();
        this.loading = true;
        this.activeGenerationRunId = runId;
        this.chatRunStore.setActiveRunId(runId);
        this.ensureRuntime(runId);
        this.scheduleScrollToBottom();

        const transportPayload = {
            ...userMessage,
            run_id: runId,
            actor_user_uuid: this.getActorUserUuid(),
            media: mediaPayload.map((media) => this.serializeMediaForTransport(media)),
            context_attachments: this.contextAttachments.map((item) => ({ ...item })),
            feature_flags: {
                image_generation: this.imageGenerationEnabled,
                code_interpreter: this.codeInterpreterEnabled,
            },
        };

        this.websocketService.send(JSON.stringify({
            action: 'send_message',
            payload: transportPayload,
        }));

        this.resetAttachments();
        this.resetComposerContext();
    }

    closeLargeMessagePrompt(): void {
        this.largeMessagePromptOpen = false;
        this.pendingLargeMessageText = null;
    }

    sendLargeMessageInline(): void {
        this.largeMessagePromptOpen = false;
        this.skipLargeMessagePromptOnce = true;
        void this.sendMessage();
    }

    async sendLargeMessageAsAttachment(): Promise<void> {
        const text = this.pendingLargeMessageText || String(this.chatInput.value || '').trim();
        if (!text) {
            this.closeLargeMessagePrompt();
            return;
        }
        try {
            const attachment = await this.buildTextAttachmentFromContent(text);
            this.attachments = [...this.attachments, attachment];
            this.chatInput.setValue('Прикрепил длинный текст как документ.');
            this.resetTextareaHeight();
            this.largeMessagePromptOpen = false;
            this.pendingLargeMessageText = null;
            this.skipLargeMessagePromptOnce = true;
            void this.sendMessage();
        } catch {
            this.notificationService.open({
                type: 'error',
                message: 'Не удалось подготовить текстовый документ.',
                autoClose: true,
            });
        }
    }

    copyMessage(msg: Message): void {
        const text = this.getMessageCopyText(msg);
        if (!text) {
            return;
        }
        navigator.clipboard.writeText(text).then(() => {
            this.notificationService.open({
                type: 'success',
                title: 'Сообщение скопировано',
                autoClose: true,
                duration: 1200,
            });
        }).catch(() => {
            this.notificationService.open({
                type: 'error',
                title: 'Не удалось скопировать сообщение',
                autoClose: true,
                duration: 1800,
            });
        });
    }

    private getMessageCopyText(msg: Message): string {
        const content = String(msg?.content || '').trim();
        if (!content) {
            return '';
        }
        if (msg.role === 'assistant') {
            return content.replace(/<think>[\s\S]*?<\/think>/gi, '').trim() || content;
        }
        return content;
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

    skipThinking(): void {
        if (!this.activeGenerationRunId) {
            return;
        }
        this.websocketService.send(JSON.stringify({
            action: 'skip_thinking',
            payload: { run_id: this.activeGenerationRunId },
        }));
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
            messageId = this.chatMessageStore.findLastAssistant()?.id || null;

            if (!messageId) {
                console.warn('No assistant message found for reroll');
                return;
            }
        }

        this.loading = true;
        const runId = generateTempId();
        this.activeGenerationRunId = runId;
        this.refreshHistoryAfterRunId = runId;
        this.chatRunStore.setActiveRunId(runId);
        this.ensureRuntime(runId);

        const assistantIndex = this.chatHistory.findIndex((msg) => msg.id === messageId);
        const clientUserId = this.chatMessageStore.findLastUserIdBefore(assistantIndex);

        if (assistantIndex !== -1) {
            this.chatMessageStore.removeAssistantById(messageId);
        }

        this.scheduleScrollToBottom();

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

    canContinueMessage(msg: Message, index: number): boolean {
        return msg.role === 'assistant'
            && index === this.chatHistory.length - 1
            && !msg.isPending;
    }

    continueMessage(messageId: string): void {
        if (this.loading && this.activeGenerationRunId) {
            this.notificationService.open({
                type: 'warning',
                message: 'Сначала дождитесь завершения текущей генерации или остановите ее.',
                autoClose: true,
            });
            return;
        }
        if (!messageId) {
            return;
        }
        const runId = generateTempId();
        this.loading = true;
        this.activeGenerationRunId = runId;
        this.chatRunStore.setActiveRunId(runId);
        this.ensureRuntime(runId);
        this.scheduleScrollToBottom();
        this.websocketService.send(JSON.stringify({
            action: 'continue_message',
            payload: {
                message_id: messageId,
                run_id: runId,
                actor_user_uuid: this.getActorUserUuid(),
            },
        }));
    }

    activateMessageVariant(messageId: string): void {
        if (!messageId || this.loading) {
            return;
        }
        this.websocketService.send(JSON.stringify({
            action: 'activate_message_variant',
            payload: {
                message_id: messageId,
                actor_user_uuid: this.getActorUserUuid(),
            },
        }));
    }

    private applyActivatedMessageVariant(event: any): void {
        const groupId = String(event?.variant_group_id || '').trim();
        const current = groupId
            ? this.chatHistory.find((message) => message.variant_group_id === groupId && message.role === 'assistant')
            : undefined;
        const targetId = current?.id || event?.id;
        if (!targetId) {
            return;
        }
        this.chatMessageStore.patchById(targetId, {
            id: event.id || targetId,
            role: 'assistant',
            content: event.content || '',
            timestamp: event.timestamp || current?.timestamp || new Date().toISOString(),
            media: this.normalizeMediaList(event.media),
            parent_message_id: event.parent_message_id,
            variant_group_id: event.variant_group_id,
            variant_index: event.variant_index,
            active_variant: event.active_variant,
            variants: event.variants || current?.variants,
        });
    }

    // Voice methods
    toggleRecording() {
        if (!this.recording) {
            this.voiceService.startRecord$().subscribe({
                next: () => {
                    this.recording = true;
                },
                error: (error) => {
                    this.recording = false;
                    this.notificationService.open({
                        type: 'error',
                        title: this.getVoiceErrorMessage(error, 'Не удалось начать запись'),
                        autoClose: true,
                        duration: 1800,
                    });
                },
            });
        } else {
            this.voiceService.stopRecord$().subscribe({
                next: (res) => {
                    this.recording = false;
                    const msg = res.data;
                    if (msg && msg.content.trim()) {
                        this.scheduleScrollToBottom();
                    }
                },
                error: (error) => {
                    this.recording = false;
                    this.notificationService.open({
                        type: 'warning',
                        title: this.getVoiceErrorMessage(error, 'Запись уже остановлена'),
                        autoClose: true,
                        duration: 1800,
                    });
                },
            });
        }
    }

    private getVoiceErrorMessage(error: any, fallback: string): string {
        const detail = error?.error?.detail;
        if (typeof detail === 'string') {
            return detail;
        }
        if (detail?.message) {
            return String(detail.message);
        }
        return fallback;
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
        this.composerRef?.resizeTextarea();
    }

    onComposerExpandClick(event: Event): void {
        event.preventDefault();
        event.stopPropagation();
        this.notificationService.open({
            type: 'info',
            title: 'Расширенный редактор будет добавлен позже',
            autoClose: true,
            duration: 1600,
        });
    }

    scrollToBottom(): void {
        this.scheduleScrollToBottom();
    }

    private shouldStickToBottom(): boolean {
        const element = this.messagesContainerRef?.nativeElement;
        if (!element) {
            return true;
        }
        return isNearScrollBottom(element);
    }

    private scheduleScrollToBottom(): void {
        if (this.pendingRealtimeScroll) {
            return;
        }
        this.pendingRealtimeScroll = true;
        requestAnimationFrame(() => {
            this.pendingRealtimeScroll = false;
            this.shouldAutoScrollOnMessageFlush = false;
            const element = this.messagesContainerRef?.nativeElement;
            if (element) {
                element.scrollTop = element.scrollHeight;
            }
        });
    }

    private scheduleInitialHistoryScrollToBottom(): void {
        const scroll = () => {
            const element = this.messagesContainerRef?.nativeElement;
            if (!element) {
                return;
            }
            element.scrollTop = element.scrollHeight;
            this.syncChatScrollbarCompensation();
        };
        setTimeout(() => {
            requestAnimationFrame(() => {
                scroll();
                requestAnimationFrame(scroll);
                setTimeout(scroll, 80);
                setTimeout(scroll, 220);
            });
        }, 0);
    }

    private restoreScrollAfterHistoryPrepend(): void {
        const previous = this.pendingHistoryPrependScroll;
        this.pendingHistoryPrependScroll = null;
        if (!previous) {
            return;
        }
        requestAnimationFrame(() => {
            const element = this.messagesContainerRef?.nativeElement;
            if (!element) {
                return;
            }
            const delta = element.scrollHeight - previous.scrollHeight;
            element.scrollTop = previous.scrollTop + delta;
            this.syncChatScrollbarCompensation();
        });
    }

    private syncChatScrollbarCompensation(): void {
        const element = this.messagesContainerRef?.nativeElement;
        if (!element) {
            return;
        }
        const scrollbarWidth = Math.max(0, element.offsetWidth - element.clientWidth);
        const value = `${Math.round(scrollbarWidth)}px`;
        element.style.setProperty('--chat-scrollbar-compensation', value);
        element.parentElement?.style.setProperty('--chat-scrollbar-compensation', value);
    }

    private findMessageForRunEnd(event: any): Message | undefined {
        const currentStreamingMessage = this.chatMessageStore.currentStreamingMessage;
        const targetId = event?.id || currentStreamingMessage?.id;
        if (targetId) {
            const byId = this.chatMessageStore.findById(targetId);
            if (byId) {
                return byId;
            }
        }

        const runId = event?.run_id || currentStreamingMessage?.runId;
        if (runId) {
            const byRun = this.chatMessageStore.findAssistantByRunId(runId);
            if (byRun) {
                return byRun;
            }
        }

        return this.chatMessageStore.findLastAssistant();
    }

    private rebuildChatMessageViews(messages: Message[]): void {
        const latestUserIndex = this.findLatestUserIndex(messages);
        const total = messages.length;
        const activeIds = new Set<string>();
        const views = messages.map((msg, index) => {
            const id = msg.id || `index-${index}`;
            activeIds.add(id);
            const cached = this.chatMessageViewCache.get(id);
            const content = String(msg.content || '');
            const userContentExpandable = msg.role === 'user' && content.length > LONG_USER_MESSAGE_THRESHOLD;
            const userContentExpanded = userContentExpandable && this.expandedUserMessageIds.has(id);
            if (
                cached
                && cached.messageRef === msg
                && cached.index === index
                && cached.total === total
                && cached.latestUserIndex === latestUserIndex
                && cached.showAllSources === this.showAllChatSources
                && cached.userContentExpanded === userContentExpanded
            ) {
                return cached.view;
            }

            const isStreaming = this.isMessageStreaming(msg);
            const renderContent = userContentExpandable && !userContentExpanded
                ? `${content.slice(0, COLLAPSED_USER_MESSAGE_LENGTH).replace(/\s+$/g, '')}...`
                : content;
            const view: ChatMessageViewModel = {
                msg,
                index,
                formattedTimestamp: this.formatTimestamp(msg.timestamp),
                messageSource: this.getMessageSource(msg),
                isLatestUserMessage: index === latestUserIndex,
                isLatestAssistantMessage: index === total - 1,
                canContinue: msg.role === 'assistant' && index === total - 1 && !msg.isPending,
                hasRuntime: this.hasRuntime(msg),
                runtimeSummary: msg.runtime ? getRuntimeSummary(msg.runtime, msg.provider) : '',
                runtimeActiveLabel: getRuntimeActiveLabel(msg.runtime),
                runtimeStages: msg.runtime ? getRuntimeStages(msg.runtime) : [],
                renderContent: getStreamingRenderContent(renderContent),
                isStreaming,
                thinkingDurationMs: msg.runtime?.reasoningElapsedMs,
                collapseThinking: shouldCollapseThinkingBlock(isStreaming, content),
                userContentExpandable,
                userContentExpanded,
                hasUsageMeta: this.hasUsageMeta(msg),
                usageLines: getUsageDetailLines(msg),
            };

            this.chatMessageViewCache.set(id, {
                messageRef: msg,
                index,
                total,
                latestUserIndex,
                showAllSources: this.showAllChatSources,
                userContentExpanded,
                view,
            });
            return view;
        });

        for (const id of this.chatMessageViewCache.keys()) {
            if (!activeIds.has(id)) {
                this.chatMessageViewCache.delete(id);
            }
        }
        this.chatMessageViews.set(views);
    }

    private findLatestUserIndex(messages: Message[]): number {
        for (let i = messages.length - 1; i >= 0; i--) {
            if (messages[i]?.role === 'user') {
                return i;
            }
        }
        return -1;
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

    toggleUserMessageContent(messageId: string): void {
        if (!messageId) {
            return;
        }
        if (this.expandedUserMessageIds.has(messageId)) {
            this.expandedUserMessageIds.delete(messageId);
        } else {
            this.expandedUserMessageIds.add(messageId);
        }
        this.rebuildChatMessageViews(this.chatHistory);
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
        this.chatRunStore.setActiveRunId(runId);
        this.ensureRuntime(runId);

        const userIndex = this.chatHistory.findIndex((item) => item.id === msg.id);
        if (userIndex !== -1) {
            this.chatMessageStore.patchById(msg.id, { content: edited, isPending: true });
            this.chatMessageStore.removeAssistantAfterUserIndex(userIndex);
        }

        this.cancelEditMessage();
        this.scheduleScrollToBottom();

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
        this.activeDropdown = this.activeDropdown === 'attach' ? null : 'attach';
    }

    toggleToolsDropdown(): void {
        this.activeDropdown = this.activeDropdown === 'tools' ? null : 'tools';
    }

    toggleImageGeneration(): void {
        this.imageGenerationEnabled = !this.imageGenerationEnabled;
    }

    toggleCodeInterpreter(): void {
        this.codeInterpreterEnabled = !this.codeInterpreterEnabled;
        this.notificationService.open({
            type: 'info',
            title: this.codeInterpreterEnabled ? 'Интерпретатор кода включен как флаг' : 'Интерпретатор кода выключен',
            message: 'Backend-исполнение команд подключим отдельным этапом.',
            autoClose: true,
            duration: 1800,
        });
    }

    openFilePicker(event?: MouseEvent): void {
        event?.stopPropagation();
        this.activeDropdown = null;
        this.composerRef?.openFilePicker();
    }

    openLibraryPicker(event?: MouseEvent): void {
        event?.stopPropagation();
        this.activeDropdown = null;
        this.libraryPickerOpen = true;
        this.loadLibraryPicker();
    }

    async captureScreen(event?: MouseEvent): Promise<void> {
        event?.stopPropagation();
        this.activeDropdown = null;
        const mediaDevices = navigator.mediaDevices as MediaDevices & {
            getDisplayMedia?: (constraints?: DisplayMediaStreamOptions) => Promise<MediaStream>;
        };
        if (!mediaDevices?.getDisplayMedia) {
            this.notificationService.open({
                type: 'warning',
                message: 'Захват экрана не поддерживается этим браузером.',
                autoClose: true,
            });
            return;
        }

        let stream: MediaStream | null = null;
        try {
            stream = await mediaDevices.getDisplayMedia({ video: true, audio: false });
            const video = document.createElement('video');
            video.srcObject = stream;
            video.muted = true;
            await video.play();
            await new Promise((resolve) => setTimeout(resolve, 120));
            const width = video.videoWidth || 1280;
            const height = video.videoHeight || 720;
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            canvas.getContext('2d')?.drawImage(video, 0, 0, width, height);
            const dataUrl = canvas.toDataURL('image/png');
            const base64 = dataUrl.split(',')[1] || '';
            if (!base64) {
                throw new Error('Не удалось получить снимок экрана.');
            }
            const media: MessageMedia = {
                id: generateTempId(),
                name: `screen_${Date.now()}.png`,
                mimeType: 'image/png',
                size: Math.round((base64.length * 3) / 4),
                category: 'image',
                description: 'Screen capture',
                data: base64,
                dataUrl,
            };
            this.attachments = [...this.attachments, media];
        } catch (error) {
            const message = error instanceof Error && error.name === 'NotAllowedError'
                ? 'Захват экрана отменен.'
                : 'Не удалось сделать захват экрана.';
            this.notificationService.open({ type: 'warning', message, autoClose: true });
        } finally {
            stream?.getTracks().forEach((track) => track.stop());
        }
    }

    openWebpageModal(event?: MouseEvent): void {
        event?.stopPropagation();
        this.activeDropdown = null;
        this.webpageUrlError = '';
        this.webpageUrlControl.setValue('');
        this.webpageProcessingMode = 'extract';
        this.webpageModalOpen = true;
    }

    closeWebpageModal(): void {
        this.webpageModalOpen = false;
        this.webpageUrlError = '';
    }

    submitWebpageUrl(event?: Event): void {
        event?.preventDefault();
        const rawUrl = String(this.webpageUrlControl.value || '').trim();
        const normalized = this.normalizeWebpageUrl(rawUrl);
        if (!normalized) {
            this.webpageUrlError = 'Введите корректную ссылку http:// или https://.';
            return;
        }
        const exists = this.contextAttachments.some((item) => item.url === normalized);
        const mode = this.webpageProcessingMode;
        if (!exists) {
            this.contextAttachments = [
                ...this.contextAttachments,
                {
                    id: generateTempId(),
                    type: 'webpage',
                    title: normalized,
                    subtitle: mode === 'extract'
                        ? 'Backend загрузит страницу и извлечет текст для контекста.'
                        : 'В запрос будет передана только ссылка без загрузки страницы.',
                    url: normalized,
                    processing_mode: mode,
                    status: 'ready',
                },
            ];
        }
        this.closeWebpageModal();
    }

    attachNotes(event?: MouseEvent): void {
        event?.stopPropagation();
        this.activeDropdown = null;
        this.notificationService.open({
            type: 'info',
            title: 'Прикрепление заметок будет связано с лорбуком',
            message: 'Сейчас это пункт меню-заглушка, без подмешивания в запрос.',
            autoClose: true,
            duration: 1800,
        });
    }

    removeContextAttachment(id: string): void {
        this.contextAttachments = this.contextAttachments.filter((item) => item.id !== id);
    }

    closeLibraryPicker(): void {
        this.libraryPickerOpen = false;
        this.libraryPickerQuery = '';
    }

    loadLibraryPicker(): void {
        this.libraryPickerLoading = true;
        this.libraryService
            .list$({ q: this.libraryPickerQuery.trim(), limit: 120 })
            .pipe(finalize(() => (this.libraryPickerLoading = false)))
            .subscribe({
                next: (response) => {
                    this.libraryItems = response.items || [];
                },
                error: () => {
                    this.libraryItems = [];
                    this.notificationService.open({
                        type: 'error',
                        message: 'Не удалось открыть библиотеку.',
                        autoClose: true,
                    });
                },
            });
    }

    attachLibraryItem(item: LibraryItem): void {
        if (!item || this.isProcessingAttachments) {
            return;
        }
        this.isProcessingAttachments = true;
        this.libraryService
            .blob$(item)
            .pipe(finalize(() => (this.isProcessingAttachments = false)))
            .subscribe({
                next: async (blob) => {
                    try {
                        const dataUrl = await this.readBlobAsDataUrl(blob);
                        const base64 = dataUrl.split(',')[1] || '';
                        const media: MessageMedia = {
                            id: generateTempId(),
                            name: item.name,
                            mimeType: item.mimeType || blob.type || DEFAULT_MIME_TYPE,
                            size: item.size || blob.size,
                            category: item.category || this.determineMediaCategory(item.mimeType, item.name),
                            description: item.description,
                            data: base64,
                            dataUrl,
                        };
                        this.attachments = [...this.attachments, media];
                        this.closeLibraryPicker();
                    } catch {
                        this.notificationService.open({
                            type: 'error',
                            message: 'Не удалось подготовить файл из библиотеки.',
                            autoClose: true,
                        });
                    }
                },
                error: () => {
                    this.notificationService.open({
                        type: 'error',
                        message: 'Не удалось загрузить файл из библиотеки.',
                        autoClose: true,
                    });
                },
            });
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
            this.composerRef?.clearFileInput();
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
        this.composerRef?.clearFileInput();
    }

    private resetComposerContext(): void {
        this.contextAttachments = [];
        this.imageGenerationEnabled = false;
        this.codeInterpreterEnabled = false;
        this.webpageUrlControl.setValue('');
        this.webpageUrlError = '';
        this.webpageModalOpen = false;
    }

    private resetTextareaHeight(): void {
        this.composerRef?.resetTextareaHeight();
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

    private async buildTextAttachmentFromContent(content: string): Promise<MessageMedia> {
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
        const dataUrl = await this.readBlobAsDataUrl(blob);
        const base64 = dataUrl.split(',')[1];
        if (!base64) {
            throw new Error('Не удалось подготовить текстовый документ.');
        }
        return {
            id: generateTempId(),
            name: `message_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`,
            mimeType: 'text/plain',
            size: blob.size,
            category: 'document',
            description: 'Long message converted to text attachment',
            data: base64,
            dataUrl,
        };
    }

    private readFileAsDataUrl(file: File): Promise<string> {
        return this.readBlobAsDataUrl(file, `Ошибка чтения файла ${file.name}.`);
    }

    private readBlobAsDataUrl(blob: Blob, errorMessage = 'Ошибка чтения файла.'): Promise<string> {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result as string);
            reader.onerror = () => reject(new Error(errorMessage));
            reader.readAsDataURL(blob);
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

    private normalizeWebpageUrl(rawUrl: string): string | null {
        if (!rawUrl) {
            return null;
        }
        const candidate = /^https?:\/\//i.test(rawUrl) ? rawUrl : `https://${rawUrl}`;
        try {
            const url = new URL(candidate);
            if (!['http:', 'https:'].includes(url.protocol)) {
                return null;
            }
            return url.toString();
        } catch {
            return null;
        }
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

    private normalizeSource(source: any): Message['source'] | undefined {
        if (!source || typeof source !== 'object') {
            return undefined;
        }
        const name = String(source.name || 'main_chat').trim().toLowerCase();
        return {
            name,
            label: String(source.label || this.formatSourceLabel(name)),
            chatId: source.chat_id ?? source.chatId,
            chatKind: source.chat_kind ?? source.chatKind,
            chatTitle: source.chat_title ?? source.chatTitle,
            messageId: source.message_id ?? source.messageId,
        };
    }

    private formatSourceLabel(name: string): string {
        const labels: Record<string, string> = {
            main_chat: 'Main chat',
            telegram: 'Telegram',
            discord: 'Discord',
            twitch: 'Twitch',
        };
        return labels[name] || name.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
    }

    getMessageSource(msg: Message): Message['source'] | undefined {
        if (!this.showAllChatSources) {
            return undefined;
        }
        return msg.source || { name: 'main_chat', label: 'Main chat' };
    }

    private readShowAllChatSources(): boolean {
        try {
            return localStorage.getItem(ChatComponent.CHAT_ALL_SOURCES_KEY) === 'true';
        } catch {
            return false;
        }
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

    getLibraryItemUrl(item: LibraryItem): string {
        return this.libraryService.resolveUrl(item);
    }

    formatMediaSize(size: number | null | undefined): string {
        const value = Number(size || 0);
        if (value >= 1024 * 1024) {
            return `${(value / 1024 / 1024).toFixed(2)} MB`;
        }
        if (value >= 1024) {
            return `${(value / 1024).toFixed(1)} KB`;
        }
        return `${value} B`;
    }

    shouldShowReroll(msg: Message, index: number): boolean {
        return msg.role === 'assistant' && index === this.chatHistory.length - 1;
    }

    hasRuntime(msg: Message): boolean {
        return !!msg.runtime && (
            msg.runtime.traces.length > 0
            || !!msg.runtime.usage
            || !!msg.runtime.meta
            || typeof msg.runtime.reasoningElapsedMs === 'number'
            || typeof msg.runtime.answerElapsedMs === 'number'
            || !!msg.runtime.model
            || !!msg.provider
        );
    }

    hasUsageMeta(msg: Message): boolean {
        const hasUsage = !!msg.runtime?.usage && Object.keys(msg.runtime.usage || {}).length > 0;
        const hasMeta = !!msg.runtime?.meta && Object.keys(msg.runtime.meta || {}).length > 0;
        return hasUsage
            || hasMeta
            || typeof msg.runtime?.reasoningElapsedMs === 'number'
            || typeof msg.runtime?.answerElapsedMs === 'number';
    }

    toggleUsageDetails(msg: Message, event: Event): void {
        event.stopPropagation();
        this.activeDropdown = null;
        this.activeUsageMessageId = this.activeUsageMessageId === msg.id ? null : msg.id;
    }

    isUsageDetailsOpen(msg: Message): boolean {
        return this.activeUsageMessageId === msg.id;
    }

    getUsageDetailLines(msg: Message): UsageDetailLine[] {
        return getUsageDetailLines(msg);
    }

    toggleRuntimeDetails(msg: Message): void {
        if (!msg.runtime) {
            return;
        }
        this.chatMessageStore.patchById(msg.id, {
            runtime: {
                ...msg.runtime,
                detailsOpen: !msg.runtime.detailsOpen,
            },
        });
    }

    getRuntimeSummary(msg: Message): string {
        const runtime = msg.runtime;
        if (!runtime) {
            return '';
        }
        return getRuntimeSummary(runtime, msg.provider);
    }

    getRuntimeStages(msg: Message): RuntimeStageView[] {
        const runtime = msg.runtime;
        if (!runtime) {
            return [];
        }
        return getRuntimeStages(runtime);
    }

    getRuntimeActiveLabel(msg: Message): string {
        return getRuntimeActiveLabel(msg.runtime);
    }

    getActiveRuntime(): RuntimeState | undefined {
        if (!this.activeGenerationRunId) {
            return undefined;
        }
        return this.chatRunStore.getRuntime(this.activeGenerationRunId);
    }

    getActiveRuntimeLabel(): string {
        const currentStreamingMessage = this.chatMessageStore.currentStreamingMessage;
        const streamContent = String(currentStreamingMessage?.content || '');
        if (currentStreamingMessage?.isPending && hasOpenThinkingBlock(streamContent)) {
            return 'Размышляю';
        }
        if (currentStreamingMessage?.isPending && hasClosedThinkingBlock(streamContent)) {
            return 'Генерирую ответ';
        }
        return getRuntimeActiveLabel(this.getActiveRuntime());
    }

    shouldShowGlobalLoadingIndicator(): boolean {
        if (!this.loading) {
            return false;
        }
        if (this.chatMessageStore.currentStreamingMessage) {
            return false;
        }
        if (!this.activeGenerationRunId) {
            return true;
        }
        return !this.chatHistory.some((msg) => (
            msg.role === 'assistant'
            && msg.runId === this.activeGenerationRunId
            && !!msg.runtime
            && ['started', 'running', 'stopping'].includes(String(msg.runtime.status))
        ));
    }

    trackByMessage(_index: number, msg: Message): string {
        return msg.id;
    }

    trackByMessageView(_index: number, item: ChatMessageViewModel): string {
        return item.msg.id;
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
        const answerElapsedMs = msg.runtime?.answerElapsedMs;
        if (!Object.keys(usage).length && !Object.keys(meta).length && typeof reasoningElapsedMs !== 'number' && typeof answerElapsedMs !== 'number') {
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
        if (typeof answerElapsedMs === 'number') {
            const secs = Math.max(0, Math.round(answerElapsedMs / 10) / 100);
            lines.push(`answer_elapsed: ${secs}s`);
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

    shouldCollapseThinking(msg: Message): boolean {
        return shouldCollapseThinkingBlock(this.isMessageStreaming(msg), String(msg.content || ''));
    }

    getMessageRenderContent(msg: Message): string {
        return getStreamingRenderContent(String(msg.content || ''));
    }

    private ensureRuntime(runId?: string | null): RuntimeState | undefined {
        return this.chatRunStore.ensureRuntime(runId);
    }

    private normalizeRuntimeTrace(event: any): RuntimeTraceEntry {
        return this.chatRunStore.normalizeRuntimeTrace(event);
    }

    private pushRuntimeTrace(runId: string, trace: RuntimeTraceEntry): void {
        const runtime = this.chatRunStore.pushRuntimeTrace(runId, trace);
        const linkedMessage = this.chatHistory.find((msg) => msg.runId === runId && msg.role === 'assistant');
        if (runtime && linkedMessage) {
            this.chatMessageStore.patchById(linkedMessage.id, { runtime });
        }
    }

    private applyRunStatus(runId: string, status: RuntimeStatus): void {
        const runtime = this.chatRunStore.applyRunStatus(runId, status);
        const linkedMessage = this.chatHistory.find((msg) => msg.runId === runId && msg.role === 'assistant');
        if (runtime && linkedMessage) {
            this.chatMessageStore.patchById(linkedMessage.id, { runtime });
        }
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
        return this.chatRunStore.hydrateRuntimeFromHistory(raw);
    }

    /** Rebuild compliance badges from a persisted runtime_meta blob
     *  (history reload path). Shapes are the snake_case summaries written
     *  by _build_compliance_meta_update on the backend. */
    private extractComplianceFromMeta(raw: any): MessageCompliance | null {
        if (!raw || typeof raw !== 'object') {
            return null;
        }
        const compliance: MessageCompliance = {};

        const validator = raw.validator;
        if (validator && typeof validator === 'object' && validator.compliance !== undefined) {
            compliance.validator = {
                compliance: Number(validator.compliance),
                acceptable: validator.acceptable ?? undefined,
                threshold: validator.threshold ?? undefined,
                violations: Array.isArray(validator.violations) ? validator.violations : [],
            };
        }

        const lang = raw.language_guard;
        if (lang && typeof lang === 'object' && lang.ok !== undefined) {
            compliance.languageGuard = {
                ok: !!lang.ok,
                detected: lang.detected || undefined,
                expected: lang.expected || undefined,
                dominance: lang.dominance ?? undefined,
            };
        }

        if (typeof raw.confidence === 'number') {
            compliance.confidence = {
                score: raw.confidence,
                threshold: raw.confidence_threshold ?? undefined,
                low: !!raw.confidence_low,
            };
        }

        const factuality = raw.factuality;
        if (factuality && typeof factuality === 'object' && factuality.supported !== undefined) {
            compliance.factuality = {
                supported: !!factuality.supported,
                sourcesFound: factuality.sources_found ?? undefined,
                claims: Array.isArray(factuality.claims) ? factuality.claims : [],
            };
        }

        return Object.keys(compliance).length > 0 ? compliance : null;
    }

    /** Normalize a live compliance_update WS payload (raw check payloads,
     *  camel-agnostic) into the Message.compliance shape. */
    private normalizeComplianceEvent(raw: any): MessageCompliance | null {
        if (!raw || typeof raw !== 'object') {
            return null;
        }
        const compliance: MessageCompliance = {};

        const validator = raw.validator;
        if (validator && typeof validator === 'object' && validator.compliance !== undefined) {
            compliance.validator = {
                compliance: Number(validator.compliance),
                acceptable: validator.acceptable ?? undefined,
                threshold: validator.threshold ?? undefined,
                violations: Array.isArray(validator.violations) ? validator.violations : [],
            };
        }

        const lang = raw.language_guard;
        if (lang && typeof lang === 'object' && lang.ok !== undefined) {
            compliance.languageGuard = {
                ok: !!lang.ok,
                detected: lang.detected || undefined,
                expected: lang.expected || undefined,
                dominance: lang.dominance ?? undefined,
            };
        }

        const confidence = raw.confidence;
        if (confidence && typeof confidence === 'object' && confidence.score !== undefined) {
            compliance.confidence = {
                score: Number(confidence.score),
                threshold: confidence.threshold ?? undefined,
                low: !!confidence.low,
            };
        }

        const factuality = raw.factuality;
        if (factuality && typeof factuality === 'object' && factuality.supported !== undefined) {
            compliance.factuality = {
                supported: !!factuality.supported,
                sourcesFound: factuality.sources_found ?? undefined,
                claims: Array.isArray(factuality.claims) ? factuality.claims : [],
            };
        }

        return Object.keys(compliance).length > 0 ? compliance : null;
    }

    trackByLibraryItem(_index: number, item: LibraryItem): string {
        return item.id;
    }
}
