import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, of } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';
import { environment } from '../../../environments/environment';
import { WebsocketService } from './websocket.service';

export interface MoralDashboardState {
    trust: number;
    stability: number;
    sociability: number;
    resentment: number;
    current_emotion: string;
    emotion_intensity: number;
    emotion_vector: Record<string, number>;
    trigger?: string;
    associated_events?: string[];
    influence?: Record<string, any>;
    affective_state?: Record<string, any>;
    updated_at?: string;
}

export interface MoralStateResponse {
    status: string;
    character: { id: string; name: string };
    state: MoralDashboardState;
    latest_snapshot: any;
    daily_summary: any;
    recent_traces: any[];
}

export interface MoralDashboardPayload {
    state: MoralDashboardState;
    latestSnapshot: any;
    dailySummary: any;
    recentTraces: any[];
}

@Injectable({
    providedIn: 'root',
})
export class MoralStateService {
    private apiUrl = environment.apiBaseUrl;
    private readonly stateSubject = new BehaviorSubject<MoralDashboardState | null>(null);
    readonly state$ = this.stateSubject.asObservable();
    private readonly dashboardSubject = new BehaviorSubject<MoralDashboardPayload | null>(null);
    readonly dashboard$ = this.dashboardSubject.asObservable();

    constructor(
        private http: HttpClient,
        private websocketService: WebsocketService
    ) {
        this.websocketService.messages$.subscribe((raw) => {
            try {
                const event = JSON.parse(raw);
                if (event?.type === 'moral_state' && event?.state) {
                    const normalized = this.normalizeState(event.state, event.timestamp);
                    if (normalized) {
                        this.stateSubject.next(normalized);
                        this.dashboardSubject.next({
                            state: normalized,
                            latestSnapshot: null,
                            dailySummary: null,
                            recentTraces: [],
                        });
                    }
                }
            } catch {
                // ignore non-json ws payloads
            }
        });
    }

    getState$(limit = 12): Observable<MoralStateResponse | null> {
        return this.http
            .get<MoralStateResponse>(`${this.apiUrl}/moral/state?limit=${limit}`)
            .pipe(
                tap((response) => {
                    if (response?.state) {
                        const normalized = this.normalizeState(response.state);
                        if (normalized) {
                            this.stateSubject.next(normalized);
                            this.dashboardSubject.next({
                                state: normalized,
                                latestSnapshot: response.latest_snapshot || null,
                                dailySummary: response.daily_summary || null,
                                recentTraces: Array.isArray(response.recent_traces) ? response.recent_traces : [],
                            });
                        }
                    }
                }),
                catchError(() => of(null))
            );
    }

    private normalizeState(raw: any, fallbackTimestamp?: string): MoralDashboardState | null {
        if (!raw || typeof raw !== 'object') {
            return null;
        }

        const metrics = raw.metrics || {};
        const trust = this.num(raw.trust, this.num(metrics.trust, 0.5));
        const stability = this.num(raw.stability, this.num(metrics.stability, 0.5));
        const sociability = this.num(raw.sociability, this.num(metrics.sociability, 0.5));
        const resentment = this.num(raw.resentment, this.num(metrics.resentment, 0));

        return {
            trust,
            stability,
            sociability,
            resentment,
            current_emotion: raw.current_emotion || 'neutral',
            emotion_intensity: this.num(raw.emotion_intensity, 0),
            emotion_vector: raw.emotion_vector || {},
            trigger: raw.trigger || raw.affective_state?.trigger,
            associated_events: Array.isArray(raw.associated_events)
                ? raw.associated_events
                : Array.isArray(raw.affective_state?.associated_events)
                    ? raw.affective_state.associated_events
                    : [],
            influence: raw.influence || raw.affective_state?.influence || {},
            affective_state: raw.affective_state || {},
            updated_at: raw.updated_at || fallbackTimestamp,
        };
    }

    private num(value: any, fallback: number): number {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : fallback;
    }
}
