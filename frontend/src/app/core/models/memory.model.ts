export interface MemoryMessagePreview {
    id: string;
    role: string;
    content: string;
    timestamp?: string | null;
}

export interface MemoryRecord {
    id: string;
    summary: string;
    dialogue_ids: string[];
    themes: string[];
    created_at?: string | null;
    updated_at?: string | null;
    score?: number;
    match_reasons?: string[];
    message_preview?: MemoryMessagePreview[];
}

export interface MemoryListResponse {
    records: MemoryRecord[];
    total: number;
    days: number;
}

export interface MemorySearchResponse {
    records: MemoryRecord[];
    total: number;
    query?: string | null;
    message_id?: string | null;
    days: number;
    generated_at?: string | null;
}

export interface MemoryRefreshResponse {
    status: string;
    records: number;
    days: number;
}

export interface MemoryTraceStep {
    stage: string;
    label: string;
    status: 'hit' | 'miss';
    scanned: number;
    hits: number;
}

export interface MemoryEmulateHit {
    id: string;
    role: string;
    content: string;
    timestamp?: string | null;
    score: number;
    details?: {
        vector_scores?: Record<string, number>;
        keyword_score?: number;
        keyword_overlap?: number;
        message_id_hit?: boolean;
    };
    from_short_term_record?: string;
    from_short_term_day?: string;
}

export interface MemoryEmulateResponse {
    status: string;
    query: string;
    message_id?: string | null;
    character: { id: string; name: string };
    settings: {
        recent_pairs: number;
        window_pairs: number;
        lookback_days: number;
        top_k: number;
        profiles: Array<{
            name: string;
            provider: string;
            model: string;
            threshold: number;
        }>;
    };
    trace: MemoryTraceStep[];
    hits: MemoryEmulateHit[];
}

export interface MemoryHistoryItem {
    id: string;
    role: string;
    content: string;
    timestamp?: string | null;
}

export interface MemoryHistoryResponse {
    status: string;
    records: MemoryHistoryItem[];
    limit: number;
    offset: number;
    has_more: boolean;
}
