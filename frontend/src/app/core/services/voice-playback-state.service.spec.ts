import { Subject } from 'rxjs';
import {
    IDLE_VOICE_PLAYBACK,
    VoicePlaybackStateService,
    nextVoicePlaybackState,
    voiceToggleAction,
} from './voice-playback-state.service';

describe('nextVoicePlaybackState', () => {
    it('ties speech to the message that is sounding', () => {
        const state = nextVoicePlaybackState(IDLE_VOICE_PLAYBACK, { stage: 'speaking', message_id: 'm1' });

        expect(state).toEqual({ stage: 'speaking', messageId: 'm1' });
    });

    it('drops the message when the voice stops speaking', () => {
        const speaking = { stage: 'speaking' as const, messageId: 'm1' };

        const state = nextVoicePlaybackState(speaking, { stage: 'listening', reason: 'tts_stopped', message_id: 'm1' });

        expect(state).toEqual(IDLE_VOICE_PLAYBACK);
    });

    it('keeps the state on a report without a known stage', () => {
        const speaking = { stage: 'speaking' as const, messageId: 'm1' };

        expect(nextVoicePlaybackState(speaking, { stage: 'preparing' })).toBe(speaking);
        expect(nextVoicePlaybackState(speaking, null)).toBe(speaking);
    });
});

describe('voiceToggleAction', () => {
    it('stops with one click the message that is sounding', () => {
        expect(voiceToggleAction({ stage: 'speaking', messageId: 'm1' }, 'm1')).toBe('stop');
    });

    it('switches when another message is sounding', () => {
        expect(voiceToggleAction({ stage: 'speaking', messageId: 'm1' }, 'm2')).toBe('switch');
    });

    it('plays when nothing is sounding', () => {
        expect(voiceToggleAction(IDLE_VOICE_PLAYBACK, 'm1')).toBe('play');
    });
});

describe('VoicePlaybackStateService', () => {
    let messages$: Subject<string>;
    let status$: Subject<any>;
    let service: VoicePlaybackStateService;

    beforeEach(() => {
        messages$ = new Subject<string>();
        status$ = new Subject<any>();
        service = new VoicePlaybackStateService(
            { messages$ } as any,
            { playbackStatus$: () => status$ } as any
        );
    });

    it('follows voice_state events from the backend', () => {
        messages$.next(JSON.stringify({ type: 'voice_state', stage: 'speaking', reason: 'tts_active', message_id: 'm1' }));
        expect(service.state).toEqual({ stage: 'speaking', messageId: 'm1' });

        messages$.next(JSON.stringify({ type: 'voice_state', stage: 'listening', reason: 'tts_idle', message_id: null }));
        expect(service.state).toEqual(IDLE_VOICE_PLAYBACK);
    });

    it('restores the sounding message when a page asks the backend', () => {
        service.refresh();
        status$.next({ status: 'ok', speaking: true, stage: 'speaking', message_id: 'm2' });

        expect(service.state).toEqual({ stage: 'speaking', messageId: 'm2' });
    });

    it('does not let a late status answer override a newer event', () => {
        service.refresh();
        messages$.next(JSON.stringify({ type: 'voice_state', stage: 'listening', reason: 'tts_idle' }));
        status$.next({ status: 'ok', speaking: true, stage: 'speaking', message_id: 'm3' });

        expect(service.state).toEqual(IDLE_VOICE_PLAYBACK);
    });

    it('ignores other websocket traffic', () => {
        messages$.next('not json');
        messages$.next(JSON.stringify({ type: 'voice_amplitude', value: 0.4 }));

        expect(service.state).toEqual(IDLE_VOICE_PLAYBACK);
    });
});
