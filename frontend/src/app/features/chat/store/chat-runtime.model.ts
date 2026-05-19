export type RuntimeStatus = 'queued' | 'started' | 'running' | 'stopping' | 'stopped' | 'completed' | 'error' | 'no_active_run' | 'skip_thinking_restarted';

export interface RuntimeTraceEntry {
    stage: string;
    state: string;
    timestamp?: string;
    elapsedMs?: number;
    details?: Record<string, any>;
}

export interface RuntimeState {
    runId: string;
    status: RuntimeStatus;
    startedAt?: string;
    finishedAt?: string;
    elapsedMs?: number;
    model?: string;
    usage?: Record<string, any> | null;
    meta?: Record<string, any> | null;
    reasoningElapsedMs?: number;
    answerElapsedMs?: number;
    detailsOpen?: boolean;
    traces: RuntimeTraceEntry[];
}
