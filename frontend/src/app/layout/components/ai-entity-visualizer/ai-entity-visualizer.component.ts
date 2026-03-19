import {
    ChangeDetectionStrategy,
    Component,
    DestroyRef,
    OnDestroy,
    OnInit,
    computed,
    inject,
    signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MoralDashboardState, MoralStateService } from '../../../core/services/moral-state.service';

@Component({
    selector: 'app-ai-entity-visualizer',
    templateUrl: './ai-entity-visualizer.component.html',
    styleUrls: ['./ai-entity-visualizer.component.less'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AiEntityVisualizerComponent implements OnInit, OnDestroy {
    private readonly destroyRef = inject(DestroyRef);
    private readonly fallbackState: MoralDashboardState = {
        trust: 0.5,
        stability: 0.7,
        sociability: 0.5,
        resentment: 0,
        current_emotion: 'neutral',
        emotion_intensity: 0.4,
        emotion_vector: {},
    };

    readonly state = signal<MoralDashboardState>(this.fallbackState);
    readonly tick = signal(0);

    readonly particles = Array.from({ length: 15 }, () => ({
        x: Math.random() * 100,
        y: Math.random() * 100,
        delay: Math.random() * 5,
    }));

    readonly breath = computed(() => {
        this.tick();
        const time = performance.now() / 1000;
        return Math.sin(time * 2) * 5;
    });

    readonly eyeOffset = computed(() => {
        this.tick();
        const time = performance.now() / 5000;
        return Math.sin(time) * 4;
    });

    readonly entityColor = computed(() => {
        const s = this.state().emotion_vector || {};
        if ((s.anger || 0) > 0.4) return '#ff6b6b';
        if ((s.joy || 0) > 0.4 || (s.happiness || 0) > 0.4) return '#d9c070';
        if ((s.sadness || 0) > 0.4 || (s.sorrow || 0) > 0.4) return '#8fb8ff';
        if ((s.irritation || 0) > 0.4) return '#ff9a4d';
        return '#9a8cff';
    });

    readonly entityGlow = computed(() => {
        const color = this.entityColor();
        return `radial-gradient(circle at center, ${color}33 0%, transparent 70%)`;
    });

    readonly entityPath = computed(() => {
        const s = this.state().emotion_vector || {};
        if ((s.anger || 0) > 0.4) {
            return 'M100,60 L130,100 L100,140 L70,100 Z M90,85 L110,85 L110,88 L90,88 Z';
        }
        if ((s.sadness || 0) > 0.4) {
            return 'M100,65 C130,65 140,120 100,145 C60,120 70,65 100,65 Z';
        }
        return 'M100,70 L125,100 L100,130 L75,100 Z';
    });

    readonly moodLabel = computed(() => this.state().current_emotion || 'neutral');
    readonly stabilityPercent = computed(() =>
        Math.round(Math.max(0, Math.min(1, this.state().stability ?? 0.7)) * 100)
    );

    private animationId: number | null = null;

    constructor(private moralStateService: MoralStateService) {}

    ngOnInit(): void {
        this.fetchState();
        this.moralStateService.state$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((nextState) => {
                if (nextState) {
                    this.state.set(nextState);
                }
            });

        const animate = () => {
            this.tick.update((v) => v + 1);
            this.animationId = window.setTimeout(animate, 80);
        };
        animate();
    }

    ngOnDestroy(): void {
        if (this.animationId !== null) {
            window.clearTimeout(this.animationId);
            this.animationId = null;
        }
    }

    private fetchState(): void {
        this.moralStateService.getState$().subscribe((response) => {
            if (response?.state) {
                this.state.set(response.state);
            }
        });
    }
}
