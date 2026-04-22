export interface DebugLogsDto {
    session_id: string;
    logs: LogsDto[];
    total?: number;
    offset?: number;
    limit?: number | null;
    has_more?: boolean;
}

export interface LogsDto {
    msg?: string;
    details: {
        context: string;
        error: string;
    }
    event_type: string;
    meta?: {
        source: string;
        severity: string;
    }
    session_id: string;
    language?: string;
    message_key?: string | null;
    timestamp: string;
    status?: string;
}
