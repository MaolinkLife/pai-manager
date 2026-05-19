import { Injectable, signal } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { Message } from '../../../core/models/message.model';
import { RuntimeState } from './chat-runtime.model';

@Injectable({ providedIn: 'root' })
export class ChatMessageStoreService {
    private static readonly STREAM_FLUSH_INTERVAL_MS = 80;

    private readonly messagesSignal = signal<Message[]>([]);
    private readonly messagesSubject = new BehaviorSubject<Message[]>([]);
    private currentStreamingMessageId: string | null = null;
    private pendingStreamingContent = '';
    private streamFlushScheduled = false;
    private lastStreamFlushAt = 0;
    private streamFlushTimer: ReturnType<typeof setTimeout> | null = null;

    readonly messagesState = this.messagesSignal.asReadonly();
    readonly messages$ = this.messagesSubject.asObservable();

    get messages(): Message[] {
        return this.messagesSignal();
    }

    get currentStreamingMessage(): Message | null {
        if (!this.currentStreamingMessageId) {
            return null;
        }
        return this.findById(this.currentStreamingMessageId) || null;
    }

    setHistory(messages: Message[]): void {
        this.currentStreamingMessageId = null;
        this.clearPendingStream();
        this.emit(messages);
    }

    prependHistory(messages: Message[]): void {
        this.emit([...messages, ...this.messages]);
    }

    push(message: Message): Message {
        this.emit([...this.messages, message]);
        return message;
    }

    upsertById(message: Message): Message {
        const messages = this.messages;
        const index = messages.findIndex((item) => item.id === message.id);
        if (index === -1) {
            return this.push(message);
        }
        const next = [...messages];
        next[index] = { ...next[index], ...message };
        this.emit(next);
        return next[index];
    }

    patchById(id: string, patch: Partial<Message>): Message | undefined {
        const messages = this.messages;
        const index = messages.findIndex((item) => item.id === id);
        if (index === -1) {
            return undefined;
        }
        const next = [...messages];
        next[index] = { ...next[index], ...patch };
        this.emit(next);
        return next[index];
    }

    deleteMessage(messageId: string, chain = false): void {
        const messages = [...this.messages];
        const index = messages.findIndex((item) => item.id === messageId);
        if (index === -1) {
            return;
        }
        const deleted = messages[index];
        messages.splice(index, 1);
        if (chain && deleted.role === 'user') {
            const assistantIndex = messages.findIndex((item, itemIndex) => itemIndex >= index && item.role === 'assistant');
            if (assistantIndex !== -1) {
                messages.splice(assistantIndex, 1);
            }
        }
        if (this.currentStreamingMessageId === messageId) {
            this.currentStreamingMessageId = null;
        }
        this.emit(messages);
    }

    removeAssistantById(messageId: string): void {
        const messages = [...this.messages];
        const index = messages.findIndex((item) => item.id === messageId && item.role === 'assistant');
        if (index === -1) {
            return;
        }
        messages.splice(index, 1);
        if (this.currentStreamingMessageId === messageId) {
            this.currentStreamingMessageId = null;
        }
        this.emit(messages);
    }

    removeAssistantAfterUserIndex(userIndex: number): void {
        const messages = [...this.messages];
        for (let i = userIndex + 1; i < messages.length; i++) {
            if (messages[i].role === 'assistant') {
                if (this.currentStreamingMessageId === messages[i].id) {
                    this.currentStreamingMessageId = null;
                }
                messages.splice(i, 1);
                this.emit(messages);
                return;
            }
        }
    }

    startStreaming(message: Message): Message {
        const existing = this.findById(message.id);
        if (existing) {
            this.currentStreamingMessageId = existing.id;
            return existing;
        }
        this.currentStreamingMessageId = message.id;
        return this.push(message);
    }

    appendStreamingContent(content: string): Message | undefined {
        if (!this.currentStreamingMessage || !content) {
            return undefined;
        }
        this.pendingStreamingContent += content;
        this.scheduleStreamFlush();
        return this.currentStreamingMessage || undefined;
    }

    patchStreaming(patch: Partial<Message>): Message | undefined {
        this.flushPendingStream();
        const current = this.currentStreamingMessage;
        if (!current) {
            return undefined;
        }
        const next = this.patchById(current.id, patch);
        if (patch.id && patch.id !== current.id) {
            this.currentStreamingMessageId = patch.id;
        }
        return next;
    }

    finishStreaming(): void {
        this.flushPendingStream();
        this.currentStreamingMessageId = null;
    }

    findById(id?: string | null): Message | undefined {
        if (!id) {
            return undefined;
        }
        return this.messages.find((message) => message.id === id);
    }

    findAssistantByRunId(runId?: string | null): Message | undefined {
        if (!runId) {
            return undefined;
        }
        return [...this.messages].reverse().find((message) => message.role === 'assistant' && message.runId === runId);
    }

    findLastAssistant(): Message | undefined {
        return [...this.messages].reverse().find((message) => message.role === 'assistant');
    }

    findLastUserIdBefore(index: number): string | null {
        for (let i = index - 1; i >= 0; i--) {
            const candidate = this.messages[i];
            if (candidate.role === 'user' && candidate.id) {
                return candidate.id;
            }
        }
        return null;
    }

    findIndexById(id?: string | null): number {
        if (!id) {
            return -1;
        }
        return this.messages.findIndex((message) => message.id === id);
    }

    linkRuntime(runId: string, runtime: RuntimeState): void {
        const target = this.findAssistantByRunId(runId);
        if (target) {
            this.patchById(target.id, { runtime });
        }
    }

    replaceTempId(tempId: string, realId: string, patch: Partial<Message> = {}): Message | undefined {
        this.flushPendingStream();
        const current = this.findById(tempId);
        if (!current) {
            return undefined;
        }
        const messages = this.messages.map((message) => (
            message.id === tempId
                ? { ...message, ...patch, id: realId, isPending: false }
                : message
        ));
        if (this.currentStreamingMessageId === tempId) {
            this.currentStreamingMessageId = realId;
        }
        this.emit(messages);
        return this.findById(realId);
    }

    flushPendingStream(): Message | undefined {
        this.streamFlushScheduled = false;
        if (this.streamFlushTimer) {
            clearTimeout(this.streamFlushTimer);
            this.streamFlushTimer = null;
        }
        if (!this.pendingStreamingContent) {
            return this.currentStreamingMessage || undefined;
        }
        const content = this.pendingStreamingContent;
        this.pendingStreamingContent = '';
        const current = this.currentStreamingMessage;
        if (!current) {
            return undefined;
        }
        this.lastStreamFlushAt = Date.now();
        return this.patchById(current.id, { content: `${current.content || ''}${content}` });
    }

    private scheduleStreamFlush(): void {
        if (this.streamFlushScheduled) {
            return;
        }
        this.streamFlushScheduled = true;
        const elapsed = Date.now() - this.lastStreamFlushAt;
        const delay = Math.max(0, ChatMessageStoreService.STREAM_FLUSH_INTERVAL_MS - elapsed);
        this.streamFlushTimer = setTimeout(() => {
            this.streamFlushTimer = null;
            if (typeof requestAnimationFrame === 'function') {
                requestAnimationFrame(() => this.flushPendingStream());
                return;
            }
            this.flushPendingStream();
        }, delay);
    }

    private clearPendingStream(): void {
        this.pendingStreamingContent = '';
        this.streamFlushScheduled = false;
        if (this.streamFlushTimer) {
            clearTimeout(this.streamFlushTimer);
            this.streamFlushTimer = null;
        }
    }

    private emit(messages: Message[]): void {
        this.messagesSignal.set(messages);
        this.messagesSubject.next(messages);
    }
}
