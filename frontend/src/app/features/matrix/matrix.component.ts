import { Component, DestroyRef, OnInit, inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import {
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

    readonly stateMetrics = [
        { key: 'trust', color: 'metric--trust' },
        { key: 'stability', color: 'metric--stability' },
        { key: 'sociability', color: 'metric--sociability' },
        { key: 'resentment', color: 'metric--resentment' },
    ];

    readonly emotionBars = [
        { key: 'joy', color: 'emotion--joy' },
        { key: 'sadness', color: 'emotion--sadness' },
        { key: 'anger', color: 'emotion--anger' },
        { key: 'irritation', color: 'emotion--irritation' },
        { key: 'happiness', color: 'emotion--happiness' },
        { key: 'sorrow', color: 'emotion--sorrow' },
        { key: 'grief', color: 'emotion--grief' },
        { key: 'jealousy', color: 'emotion--jealousy' },
    ];

    constructor(
        private moralStateService: MoralStateService,
        private localizationService: LocalizationService
    ) {}

    ngOnInit(): void {
        this.localizationService.init();
        this.moralStateService.state$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((nextState) => {
                if (nextState) {
                    this.state = nextState;
                }
            });
        this.loadState();
    }

    loadState(): void {
        this.isLoading = true;
        this.moralStateService.getState$().subscribe((response) => {
            this.state = response?.state || null;
            this.isLoading = false;
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

    get coherencePercent(): number {
        return Math.round(this.getMetricValue('stability') * 100);
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
}
