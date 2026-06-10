import { Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
    MoralDashboardPayload,
    MoralDashboardState,
    MoralStateService,
} from '../../core/services/moral-state.service';
import { LocalizationService } from '../../shared/pipes/translation/localization.service';

@Component({
    selector: 'app-matrix',
    templateUrl: './matrix.component.html',
    styleUrls: ['./matrix.component.less'],
})
export class MatrixComponent implements OnInit {
    private readonly destroyRef = inject(DestroyRef);
    isLoading = true;
    state: MoralDashboardState | null = null;
    latestSnapshot: any = null;
    dailySummary: any = null;
    recentTraces: any[] = [];

    readonly stateMetrics = [
        { key: 'trust', color: 'metric--trust' },
        { key: 'stability', color: 'metric--stability' },
        { key: 'sociability', color: 'metric--sociability' },
        { key: 'resentment', color: 'metric--resentment' },
    ];

    readonly emotionBars = [
        { key: 'longing', color: 'emotion--sorrow' },
        { key: 'joy', color: 'emotion--joy' },
        { key: 'frustration', color: 'emotion--irritation' },
        { key: 'sadness', color: 'emotion--sadness' },
        { key: 'embarrassment', color: 'emotion--happiness' },
        { key: 'anxiety', color: 'emotion--anger' },
        { key: 'peace', color: 'emotion--joy' },
        { key: 'confusion', color: 'emotion--grief' },
        { key: 'pride', color: 'emotion--happiness' },
        { key: 'resentment', color: 'emotion--irritation' },
        { key: 'tenderness', color: 'emotion--joy' },
        { key: 'jealousy', color: 'emotion--jealousy' },
    ];

    constructor(
        private moralStateService: MoralStateService,
        private localizationService: LocalizationService
    ) {}

    ngOnInit(): void {
        this.localizationService.init();
        this.moralStateService.dashboard$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((payload: MoralDashboardPayload | null) => {
                if (payload?.state) {
                    this.applyPayload(payload);
                }
            });
        this.loadState();
    }

    loadState(): void {
        this.isLoading = true;
        this.moralStateService.getState$().subscribe({
            next: (response) => {
                if (response?.state) {
                    this.applyPayload({
                        state: response.state,
                        latestSnapshot: response.latest_snapshot || null,
                        dailySummary: response.daily_summary || null,
                        recentTraces: Array.isArray(response.recent_traces) ? response.recent_traces : [],
                    });
                } else {
                    this.state = null;
                    this.recomputeDerived();
                }
                this.isLoading = false;
            },
            error: () => {
                this.isLoading = false;
            },
        });
    }

    getMetricValue(key: string): number {
        const raw = Number((this.state as any)?.[key] ?? 0);
        return this.clamp01(raw);
    }

    getEmotionValue(key: string): number {
        const raw = Number(this.state?.emotion_vector?.[key] ?? 0);
        return this.clamp01(raw);
    }

    // ВАЖНО: всё ниже — поля, а не геттеры. Геттеры, возвращающие новые
    // массивы/объекты на каждый вызов, в паре с *ngFor без trackBy
    // пересоздавали DOM-строки на каждом change detection. Каждая новая
    // строка создавала новые инстансы impure translate-пайпа, чей effect()
    // дёргает markForCheck → новый CD → новый массив → новые строки —
    // бесконечная CD-петля, наглухо вешавшая renderer. Поля пересчитываются
    // один раз в applyPayload.
    coherencePercent = 0;
    latestTrace: any = null;
    traceCount = 0;
    affectiveTrigger = '';
    influenceEntries: Array<{ key: string; value: any }> = [];
    associatedEvents: string[] = [];
    latestTraceCause = '';
    latestTraceOutcomes: any[] = [];

    trackByInfluence(_index: number, item: { key: string; value: any }): string {
        return item.key;
    }

    formatUpdatedAt(value: string | null | undefined): string {
        if (!value) {
            return '';
        }

        let normalized = String(value).trim();
        const hasTimezone = /([zZ]|[+\-]\d{2}:\d{2})$/.test(normalized);
        if (!hasTimezone && normalized.includes('T')) {
            normalized = `${normalized}Z`;
        }

        const parsed = new Date(normalized);
        if (Number.isNaN(parsed.getTime())) {
            return value;
        }

        const locale = this.localizationService.currentLang() || 'ru-RU';
        return new Intl.DateTimeFormat(locale, {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        }).format(parsed);
    }

    private clamp01(value: number): number {
        if (Number.isNaN(value)) {
            return 0;
        }
        return Math.min(Math.max(value, 0), 1);
    }

    private formatTraceCause(value: any): string {
        const raw = String(value || '').replace(/\s+/g, ' ').trim();
        if (!raw) {
            return '';
        }
        const lower = raw.toLowerCase();
        const internalMarkers = [
            'this is a proactive private check-in',
            'send one short natural message only',
            'avoid guilt-tripping',
        ];
        if (internalMarkers.some((marker) => lower.includes(marker))) {
            return 'внутренний proactive check-in';
        }
        return raw;
    }

    private applyPayload(payload: MoralDashboardPayload): void {
        this.state = payload.state || null;
        this.latestSnapshot = payload.latestSnapshot || null;
        this.dailySummary = payload.dailySummary || null;
        this.recentTraces = Array.isArray(payload.recentTraces) ? payload.recentTraces : [];
        this.recomputeDerived();
    }

    private recomputeDerived(): void {
        this.coherencePercent = Math.round(this.getMetricValue('stability') * 100);
        this.latestTrace = this.recentTraces[0] || null;
        this.traceCount = this.recentTraces.length;
        this.affectiveTrigger = String(
            this.state?.trigger || this.state?.affective_state?.['trigger'] || ''
        ).trim();

        const influence = this.state?.influence || this.state?.affective_state?.['influence'] || {};
        this.influenceEntries =
            influence && typeof influence === 'object'
                ? Object.entries(influence).map(([key, value]) => ({ key, value }))
                : [];

        const events = this.state?.associated_events || this.state?.affective_state?.['associated_events'] || [];
        this.associatedEvents = Array.isArray(events) ? events.map((item) => String(item)) : [];

        this.latestTraceCause = this.formatTraceCause(this.latestTrace?.cause);

        const notes = this.latestTrace?.notes;
        const outcomes = notes && typeof notes === 'object' ? notes.outcomes : [];
        this.latestTraceOutcomes = Array.isArray(outcomes) ? outcomes : [];
    }
}
