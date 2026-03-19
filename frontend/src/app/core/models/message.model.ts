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

export interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
    isPending?: boolean;
    media?: MessageMedia[];
    runId?: string;
    provider?: string;
    reasoning?: string;
    stopped?: boolean;
    runtime?: {
        runId: string;
        status: 'started' | 'running' | 'stopping' | 'stopped' | 'completed' | 'error' | 'no_active_run';
        startedAt?: string;
        finishedAt?: string;
        elapsedMs?: number;
        model?: string;
        usage?: Record<string, any> | null;
        meta?: Record<string, any> | null;
        reasoningElapsedMs?: number;
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
