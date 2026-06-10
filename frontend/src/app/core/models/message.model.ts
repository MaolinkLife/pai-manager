export type MessageMediaCategory = 'image' | 'audio' | 'video' | 'document' | 'other';

export interface MessageMedia {
    id: string;
    name: string;
    mimeType: string;
    size: number;
    category: MessageMediaCategory;
    description?: string;
    url?: string;
    data?: string;
    dataUrl?: string;
}

export interface MessageCompliance {
    validator?: {
        compliance?: number;
        acceptable?: boolean;
        threshold?: number;
        violations?: string[];
    };
    languageGuard?: {
        ok?: boolean;
        detected?: string;
        expected?: string;
        dominance?: number;
    };
    confidence?: {
        score?: number;
        threshold?: number;
        low?: boolean;
    };
    factuality?: {
        supported?: boolean;
        sourcesFound?: number;
        claims?: string[];
    };
}

export interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    isPending?: boolean;
    compliance?: MessageCompliance | null;
    media?: MessageMedia[];
    runId?: string;
    provider?: string;
    reasoning?: string;
    stopped?: boolean;
    parent_message_id?: string | null;
    variant_group_id?: string | null;
    variant_index?: number | null;
    active_variant?: boolean;
    variants?: {
        group_id: string;
        count: number;
        active_id: string;
        active_index: number;
        items: Array<{
            id: string;
            index: number;
            active: boolean;
        }>;
    } | null;
    source?: {
        name: string;
        label: string;
        chatId?: number | string;
        chatKind?: string;
        chatTitle?: string;
        messageId?: number | string;
    };
    runtime?: {
        runId: string;
        status: 'queued' | 'started' | 'running' | 'stopping' | 'stopped' | 'completed' | 'error' | 'no_active_run' | 'skip_thinking_restarted';
        startedAt?: string;
        finishedAt?: string;
        elapsedMs?: number;
        model?: string;
        usage?: Record<string, any> | null;
        meta?: Record<string, any> | null;
        reasoningElapsedMs?: number;
        answerElapsedMs?: number;
        detailsOpen?: boolean;
        traces: Array<{
            stage: string;
            state: string;
            timestamp?: string;
            elapsedMs?: number;
            details?: Record<string, any>;
        }>;
    };
}
