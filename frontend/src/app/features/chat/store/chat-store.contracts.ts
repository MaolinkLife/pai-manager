import { Message, MessageMedia } from '../../../core/models/message.model';
import { RuntimeStatus } from './chat-runtime.model';

export interface ChatWsBaseEvent {
    type: string;
    run_id?: string;
    timestamp?: string;
}

export interface ChatWsMessageChunkEvent extends ChatWsBaseEvent {
    type: 'message_chunk';
    role: 'assistant';
    content?: string;
    media?: MessageMedia[];
    source?: unknown;
    id?: string;
}

export interface ChatWsMessageEvent extends ChatWsBaseEvent {
    type: 'message';
    id: string;
    role: 'user' | 'assistant';
    content: string;
    provider?: string;
    media?: MessageMedia[];
    source?: unknown;
    parent_message_id?: string | null;
    variant_group_id?: string | null;
    variant_index?: number | null;
    active_variant?: boolean;
    variants?: Message['variants'];
}

export interface ChatWsMessageEndEvent extends ChatWsBaseEvent {
    type: 'message_end';
    id?: string;
    provider?: string;
    model?: string;
    stopped?: boolean;
    voice_playback_started?: boolean;
    reasoning?: string;
    usage?: Record<string, any>;
    meta?: Record<string, any>;
    reasoning_elapsed_ms?: number;
    answer_elapsed_ms?: number;
}

export interface ChatWsRuntimeTraceEvent extends ChatWsBaseEvent {
    type: 'runtime_trace';
    stage?: string;
    action?: string;
    tool?: string;
    state?: string;
    status?: string;
    elapsed_ms?: number;
    elapsedMs?: number;
    details?: Record<string, any>;
}

export interface ChatWsRunStatusEvent extends ChatWsBaseEvent {
    type: 'run_status';
    status: RuntimeStatus;
}

export type ChatWsEvent =
    | ChatWsMessageChunkEvent
    | ChatWsMessageEvent
    | ChatWsMessageEndEvent
    | ChatWsRuntimeTraceEvent
    | ChatWsRunStatusEvent
    | (ChatWsBaseEvent & Record<string, any>);
