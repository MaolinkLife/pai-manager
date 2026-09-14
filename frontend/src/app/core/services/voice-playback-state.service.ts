import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { VoiceService } from './voice.service';
import { WebsocketService } from './websocket.service';

export type VoiceStage = 'listening' | 'waiting' | 'speaking';

export interface VoicePlaybackState {
    stage: VoiceStage;
    /** Chat message being voiced right now; null when no chat message is sounding. */
    messageId: string | null;
}

export const IDLE_VOICE_PLAYBACK: VoicePlaybackState = { stage: 'listening', messageId: null };

export type VoiceToggleAction = 'play' | 'stop' | 'switch';

const KNOWN_STAGES: ReadonlySet<string> = new Set(['listening', 'waiting', 'speaking']);

/** State after a backend voice report: a `voice_state` WS event or /voice/playback/status. */
export function nextVoicePlaybackState(current: VoicePlaybackState, report: any): VoicePlaybackState {
    const stage = String(report?.stage || '');
    if (!KNOWN_STAGES.has(stage)) {
        return current;
    }
    const messageId = stage === 'speaking' && report?.message_id ? String(report.message_id) : null;
    return { stage: stage as VoiceStage, messageId };
}

/** What a click on a message's voice button does. */
export function voiceToggleAction(state: VoicePlaybackState, messageId: string): VoiceToggleAction {
    if (state.stage === 'speaking' && state.messageId === messageId) {
        return 'stop';
    }
    return state.stage === 'speaking' ? 'switch' : 'play';
}

/**
 * The backend voice state, kept for the whole app: a page that is left and
 * opened again shows what is really sounding instead of guessing.
 */
@Injectable({
    providedIn: 'root',
})
export class VoicePlaybackStateService {
    private readonly stateSubject = new BehaviorSubject<VoicePlaybackState>(IDLE_VOICE_PLAYBACK);
    readonly state$ = this.stateSubject.asObservable();
    private eventsReceived = 0;

    constructor(
        private websocketService: WebsocketService,
        private voiceService: VoiceService
    ) {
        this.websocketService.messages$.subscribe((raw) => {
            let event: any;
            try {
                event = JSON.parse(raw);
            } catch {
                return;
            }
            if (event?.type === 'voice_state') {
                this.eventsReceived += 1;
                this.apply(event);
            }
        });
    }

    get state(): VoicePlaybackState {
        return this.stateSubject.value;
    }

    /** Ask the backend what is sounding now. A live event that arrives first wins. */
    refresh(): void {
        const eventsBefore = this.eventsReceived;
        this.voiceService.playbackStatus$().subscribe({
            next: (status) => {
                if (this.eventsReceived === eventsBefore) {
                    this.apply(status);
                }
            },
            error: (err) => console.warn('[Voice] Playback status request failed', err),
        });
    }

    private apply(report: any): void {
        const current = this.stateSubject.value;
        const next = nextVoicePlaybackState(current, report);
        if (next.stage !== current.stage || next.messageId !== current.messageId) {
            this.stateSubject.next(next);
        }
    }
}
