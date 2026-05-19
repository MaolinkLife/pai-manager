import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { RuntimeState, RuntimeStatus, RuntimeTraceEntry } from './chat-runtime.model';

@Injectable({ providedIn: 'root' })
export class ChatRunStoreService {
    private readonly runtimeByRunId = new Map<string, RuntimeState>();
    private readonly runtimeByRunIdSubject = new BehaviorSubject<Map<string, RuntimeState>>(new Map());
    private readonly activeRunIdSubject = new BehaviorSubject<string | null>(null);

    readonly runtimeByRunId$ = this.runtimeByRunIdSubject.asObservable();
    readonly activeRunId$ = this.activeRunIdSubject.asObservable();

    setActiveRunId(runId: string | null): void {
        this.activeRunIdSubject.next(runId);
    }

    getActiveRunId(): string | null {
        return this.activeRunIdSubject.getValue();
    }

    ensureRuntime(runId?: string | null): RuntimeState | undefined {
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
        this.emit();
        return runtime;
    }

    getRuntime(runId?: string | null): RuntimeState | undefined {
        if (!runId) {
            return undefined;
        }
        return this.runtimeByRunId.get(runId);
    }

    setRuntime(runId: string, runtime: RuntimeState): void {
        this.runtimeByRunId.set(runId, runtime);
        this.emit();
    }

    patchMessageEnd(runId: string, event: any): RuntimeState | undefined {
        const runtime = this.ensureRuntime(runId);
        if (!runtime) {
            return undefined;
        }
        runtime.status = event?.stopped ? 'stopped' : 'completed';
        runtime.finishedAt = event?.timestamp || new Date().toISOString();
        runtime.model = event?.model || runtime.model;
        runtime.usage = event?.usage || runtime.usage;
        runtime.meta = event?.meta || runtime.meta;
        runtime.reasoningElapsedMs = typeof event?.reasoning_elapsed_ms === 'number'
            ? event.reasoning_elapsed_ms
            : runtime.reasoningElapsedMs;
        runtime.answerElapsedMs = typeof event?.answer_elapsed_ms === 'number'
            ? event.answer_elapsed_ms
            : runtime.answerElapsedMs;
        runtime.detailsOpen = false;
        this.emit();
        return runtime;
    }

    normalizeRuntimeTrace(event: any): RuntimeTraceEntry {
        const rawStage = String(event?.stage || event?.action || event?.tool || 'unknown')
            .trim()
            .toLowerCase()
            .replace(/[^a-z0-9_.:-]+/g, '_');
        const stageAliases: Record<string, string> = {
            media: 'vision',
            visual: 'vision',
            tool: 'decision',
            tools: 'decision',
            prompt_builder: 'image_prompt',
            image: 'image_generation',
            model: 'generation',
            llm: 'generation',
        };
        const stage = stageAliases[rawStage] || rawStage;

        const rawState = String(event?.state || event?.status || 'info').trim().toLowerCase();
        const stateAliases: Record<string, string> = {
            started: 'start',
            running: 'start',
            active: 'start',
            pending: 'start',
            completed: 'end',
            complete: 'end',
            done: 'end',
            success: 'end',
            failed: 'error',
            failure: 'error',
        };
        const state = stateAliases[rawState] || rawState;

        return {
            stage,
            state,
            timestamp: event?.timestamp,
            elapsedMs: typeof event?.elapsed_ms === 'number'
                ? event.elapsed_ms
                : (typeof event?.elapsedMs === 'number' ? event.elapsedMs : undefined),
            details: this.sanitizeRuntimeDetails(event?.details),
        };
    }

    pushRuntimeTrace(runId: string, trace: RuntimeTraceEntry): RuntimeState | undefined {
        const runtime = this.ensureRuntime(runId);
        if (!runtime) {
            return undefined;
        }
        const last = runtime.traces[runtime.traces.length - 1];
        if (
            last
            && last.stage === trace.stage
            && last.state === trace.state
            && last.elapsedMs === trace.elapsedMs
            && JSON.stringify(last.details || {}) === JSON.stringify(trace.details || {})
        ) {
            return runtime;
        }
        runtime.traces = [...runtime.traces, trace];
        if (trace.state === 'end' && typeof trace.elapsedMs === 'number' && trace.stage === 'pipeline') {
            runtime.elapsedMs = trace.elapsedMs;
        }
        if (trace.state === 'start' && trace.stage === 'pipeline' && !runtime.startedAt) {
            runtime.startedAt = trace.timestamp || new Date().toISOString();
        }
        this.emit();
        return runtime;
    }

    applyRunStatus(runId: string, status: RuntimeStatus): RuntimeState | undefined {
        const runtime = this.ensureRuntime(runId);
        if (!runtime) {
            return undefined;
        }
        runtime.status = status;
        if (status === 'completed' || status === 'stopped' || status === 'error') {
            runtime.finishedAt = new Date().toISOString();
            if (typeof runtime.elapsedMs !== 'number') {
                runtime.elapsedMs = this.estimateElapsedMs(runtime);
            }
        }
        this.emit();
        return runtime;
    }

    hydrateRuntimeFromHistory(raw: any): RuntimeState | undefined {
        if (!raw || typeof raw !== 'object') {
            return undefined;
        }
        const tracesRaw = Array.isArray(raw.traces) ? raw.traces : [];
        const traces: RuntimeTraceEntry[] = tracesRaw.map((trace: any) => this.normalizeRuntimeTrace(trace));
        const runId = raw.run_id || raw.runId;
        if (!runId) {
            return undefined;
        }
        return {
            runId,
            status: raw.stopped ? 'stopped' : 'completed',
            startedAt: raw.started_at || raw.startedAt || undefined,
            finishedAt: raw.timestamp || raw.finishedAt || undefined,
            elapsedMs: typeof raw.elapsed_ms === 'number' ? raw.elapsed_ms : (typeof raw.elapsedMs === 'number' ? raw.elapsedMs : undefined),
            model: raw.model || undefined,
            usage: raw.usage || null,
            meta: raw.meta || null,
            reasoningElapsedMs: typeof raw.reasoning_elapsed_ms === 'number'
                ? raw.reasoning_elapsed_ms
                : (typeof raw.reasoningElapsedMs === 'number' ? raw.reasoningElapsedMs : undefined),
            answerElapsedMs: typeof raw.answer_elapsed_ms === 'number'
                ? raw.answer_elapsed_ms
                : (typeof raw.answerElapsedMs === 'number' ? raw.answerElapsedMs : undefined),
            detailsOpen: false,
            traces,
        };
    }

    private sanitizeRuntimeDetails(details: any): Record<string, any> | undefined {
        if (!details || typeof details !== 'object' || Array.isArray(details)) {
            return undefined;
        }
        const allowed = ['provider', 'model', 'usage', 'bytes', 'description_length', 'file_count', 'media_count', 'route', 'mode', 'error'];
        const sanitized: Record<string, any> = {};
        for (const key of allowed) {
            const value = details[key];
            if (value === undefined || value === null || value === '') {
                continue;
            }
            sanitized[key] = typeof value === 'object'
                ? JSON.parse(JSON.stringify(value))
                : String(value).slice(0, 260);
        }
        return Object.keys(sanitized).length ? sanitized : undefined;
    }

    private estimateElapsedMs(runtime: RuntimeState): number {
        const started = runtime.startedAt ? new Date(runtime.startedAt).getTime() : Date.now();
        const finished = runtime.finishedAt ? new Date(runtime.finishedAt).getTime() : Date.now();
        return Math.max(0, finished - started);
    }

    private emit(): void {
        this.runtimeByRunIdSubject.next(new Map(this.runtimeByRunId));
    }
}
