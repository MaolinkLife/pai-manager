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
import { EMPTY } from 'rxjs';
import { MoralDashboardState, MoralStateService } from '../../../core/services/moral-state.service';
import { AuthService } from '../../../core/services/auth.service';
import { VoiceService } from '../../../core/services/voice.service';
import { WebsocketService } from '../../../core/services/websocket.service';
import { LocalizationService } from '../../../shared/pipes/translation/localization.service';

type CallStage = 'listening' | 'waiting' | 'speaking';

@Component({
    selector: 'app-ai-entity-visualizer',
    templateUrl: './ai-entity-visualizer.component.html',
    styleUrls: ['./ai-entity-visualizer.component.less'],
    changeDetection: ChangeDetectionStrategy.OnPush,
    standalone: false
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
    readonly speaking = signal(false);

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

    // Real loudness from the backend playback loop (voice_amplitude events,
    // ~10/s RMS values). Smoothed towards the latest target every tick so the
    // orb glides between updates instead of stepping.
    private targetAmplitude = 0;
    readonly talk = signal(0);

    // Voice call session (блок C): VAD loop on the backend, this panel is
    // the call surface — stage chip + hang-up around the orb.
    readonly callActive = signal(false);
    readonly callBusy = signal(false);
    readonly callStage = signal<CallStage>('listening');
    readonly callStageLabel = computed(() =>
        this.t(`entityVisualizer.callStage.${this.callStage()}`)
    );

    readonly entityColor = computed(() => {
        return this.resolveMoodColor();
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

    readonly moodLabel = computed(() => this.t(`matrix.emotions.${this.state().current_emotion || 'neutral'}`));
    readonly stabilityPercent = computed(() =>
        Math.round(Math.max(0, Math.min(1, this.state().stability ?? 0.7)) * 100)
    );

    private animationId: number | null = null;
    private speakingGuardId: number | null = null;

    constructor(
        private moralStateService: MoralStateService,
        private websocketService: WebsocketService,
        private localizationService: LocalizationService,
        private voiceService: VoiceService,
        private authService: AuthService
    ) {}

    ngOnInit(): void {
        this.localizationService.init();
        // Her state and the call belong to the owner: a guest only writes.
        const owner = this.authService.isOwner();
        if (owner) {
            this.fetchState();
        }
        this.moralStateService.state$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((nextState) => {
                if (nextState) {
                    this.state.set(nextState);
                }
            });

        this.websocketService.messages$
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe((raw) => {
                try {
                    const event = JSON.parse(raw);
                    if (event?.type === 'voice_amplitude') {
                        this.onAmplitude(Number(event.value) || 0, event.done === true);
                    } else if (event?.type === 'call_state') {
                        this.callActive.set(event.active === true);
                        if (event.active === true) {
                            this.callStage.set('listening');
                        }
                    } else if (event?.type === 'voice_state' && this.callActive()) {
                        const stage = String(event.stage || '');
                        if (stage === 'listening' || stage === 'waiting' || stage === 'speaking') {
                            this.callStage.set(stage);
                        }
                    }
                } catch {
                    // ignore non-json ws payloads
                }
            });

        (owner ? this.voiceService.callStatus$() : EMPTY)
            .pipe(takeUntilDestroyed(this.destroyRef))
            .subscribe({
                next: (status) => {
                    this.callActive.set(status?.active === true);
                    const stage = String(status?.stage || '');
                    if (stage === 'listening' || stage === 'waiting' || stage === 'speaking') {
                        this.callStage.set(stage as CallStage);
                    }
                },
                error: () => {},
            });

        const animate = () => {
            this.tick.update((v) => v + 1);
            this.talk.update((value) => {
                const next = value + (this.targetAmplitude - value) * 0.45;
                return next < 0.005 ? 0 : next;
            });
            this.animationId = window.setTimeout(animate, 80);
        };
        animate();
    }

    ngOnDestroy(): void {
        if (this.animationId !== null) {
            window.clearTimeout(this.animationId);
            this.animationId = null;
        }
        if (this.speakingGuardId !== null) {
            window.clearTimeout(this.speakingGuardId);
            this.speakingGuardId = null;
        }
    }

    // The guard zeroes the amplitude if the event stream stalls (WS drop,
    // backend kill) so the orb cannot keep talking on stale data.
    private onAmplitude(value: number, done: boolean): void {
        this.targetAmplitude = done ? 0 : Math.max(0, Math.min(1, value));
        this.speaking.set(!done && this.targetAmplitude > 0.015);
        if (this.speakingGuardId !== null) {
            window.clearTimeout(this.speakingGuardId);
            this.speakingGuardId = null;
        }
        if (!done) {
            this.speakingGuardId = window.setTimeout(() => {
                this.targetAmplitude = 0;
                this.speaking.set(false);
                this.speakingGuardId = null;
            }, 700);
        }
    }

    startCall(): void {
        if (this.callBusy() || this.callActive()) {
            return;
        }
        this.callBusy.set(true);
        this.voiceService.callStart$().subscribe({
            next: (response) => {
                this.callBusy.set(false);
                if (response?.active) {
                    this.callActive.set(true);
                    this.callStage.set('listening');
                }
            },
            error: () => this.callBusy.set(false),
        });
    }

    endCall(): void {
        if (this.callBusy()) {
            return;
        }
        this.callBusy.set(true);
        this.voiceService.callStop$().subscribe({
            next: () => {
                this.callBusy.set(false);
                this.callActive.set(false);
            },
            error: () => this.callBusy.set(false),
        });
    }

    private fetchState(): void {
        this.moralStateService.getState$().subscribe((response) => {
            if (response?.state) {
                this.state.set(response.state);
            }
        });
    }

    t(key: string): string {
        return this.localizationService.t(key);
    }

    private resolveMoodColor(): string {
        const current = String(this.state().current_emotion || '').toLowerCase();
        const vector = this.state().emotion_vector || {};
        const resentment = Number(this.state().resentment || 0);

        const candidates: Array<{ keys: string[]; color: string; threshold: number }> = [
            { keys: ['anger', 'angry', 'rage'], color: '#ff5b62', threshold: 0.25 },
            { keys: ['playful', 'flirty', 'seductive', 'teasing', 'excited'], color: '#b56cff', threshold: 0.25 },
            { keys: ['sadness', 'sad', 'sorrow', 'grief', 'melancholy'], color: '#6aa8ff', threshold: 0.25 },
            { keys: ['joy', 'happiness', 'happy', 'delight'], color: '#ffd24d', threshold: 0.25 },
            { keys: ['resentment', 'offended', 'hurt'], color: '#62d184', threshold: 0.2 },
            { keys: ['disgust', 'disgusted'], color: '#c0a36e', threshold: 0.25 },
            { keys: ['irritation', 'annoyed'], color: '#ff9a4d', threshold: 0.25 },
        ];

        for (const candidate of candidates) {
            if (candidate.keys.includes(current)) {
                return candidate.color;
            }
            if (candidate.keys.some((key) => Number(vector[key] || 0) >= candidate.threshold)) {
                return candidate.color;
            }
        }

        if (resentment >= 0.25) {
            return '#62d184';
        }
        return '#d7bd66';
    }
}
