import { TestBed } from '@angular/core/testing';
import { Subject, of } from 'rxjs';
import { ChatComponent } from './chat.component';
import { ChatMessageStoreService, ChatRunStoreService, ChatSessionStateService } from './store';

describe('ChatComponent: a busy chat and a dropped connection', () => {
    let sent: any[];
    let reconnected$: Subject<void>;
    let session: ChatSessionStateService;

    function create(owner = true): ChatComponent {
        sent = [];
        reconnected$ = new Subject<void>();
        session = new ChatSessionStateService();
        const websocketService: any = {
            isConnected: () => true,
            send: (raw: string) => sent.push(JSON.parse(raw)),
            reconnect: () => undefined,
            reconnected$,
            bufferedMessages$: new Subject(),
            getBufferedMessagesAfter: () => [],
            getConsumerCursor: () => 0,
        };
        const authService: any = {
            isOwner: () => owner,
            getCurrentUser: () => ({ uuid: owner ? 'owner-uuid' : 'guest-uuid', name: 'Guest' }),
        };
        const configService: any = { getConfig$: () => of(null) };
        const voiceService: any = { voiceModeStatus$: () => of({ running: false }) };
        const voicePlaybackState: any = { state$: of({ stage: 'idle', messageId: null }), refresh: () => undefined };
        const notifications: any = { open: () => undefined };
        const component = TestBed.runInInjectionContext(() => new ChatComponent(
            {} as any,
            authService,
            configService,
            {} as any,
            {} as any,
            voiceService,
            voicePlaybackState,
            websocketService,
            notifications,
            new ChatRunStoreService(),
            new ChatMessageStoreService(),
            session,
        ));
        component.ngOnInit();
        sent = [];
        return component;
    }

    it('sends a message while a reply is still being written', async () => {
        const component = create();
        session.generationActive = true;
        session.activeGenerationRunId = 'm1';
        component.chatInput.setValue('one more thing');

        await component.sendMessage();

        expect(sent.map((item) => item.action)).toEqual(['send_message']);
        expect(sent[0].payload.content).toBe('one more thing');
    });

    it('stop asks the server for the reply being written, not for the message sent last', () => {
        const component = create();
        session.activeGenerationRunId = 'm2';

        component.stopGeneration();

        expect(sent).toEqual([{ action: 'stop_generation', payload: {} }]);
    });

    it('skipping the thinking asks the server for the reply being written', () => {
        const component = create();
        session.activeGenerationRunId = 'm2';

        component.skipThinking();

        expect(sent).toEqual([{ action: 'skip_thinking', payload: {} }]);
    });

    it('after a dropped connection the chat unfreezes and reloads what the server saved', () => {
        const component = create();
        session.generationActive = true;
        session.activeGenerationRunId = 'm1';

        reconnected$.next();

        expect(component.loading).toBeFalse();
        expect(component.activeGenerationRunId).toBeNull();
        expect(sent.map((item) => item.action)).toEqual(['fetch_history']);
    });

    it('a guest chat unfreezes too, with no stored history to reload', () => {
        const component = create(false);
        session.generationActive = true;
        session.activeGenerationRunId = 'g1';

        reconnected$.next();

        expect(component.loading).toBeFalse();
        expect(component.activeGenerationRunId).toBeNull();
        expect(sent).toEqual([]);
    });
});

describe('ChatComponent: the history source filter event', () => {
    function create(): ChatComponent {
        const websocketService: any = {
            isConnected: () => true,
            send: () => undefined,
            reconnect: () => undefined,
            reconnected$: new Subject<void>(),
            bufferedMessages$: new Subject(),
            getBufferedMessagesAfter: () => [],
            getConsumerCursor: () => 0,
        };
        const authService: any = {
            isOwner: () => true,
            getCurrentUser: () => ({ uuid: 'owner-uuid', name: 'Owner' }),
        };
        const configService: any = { getConfig$: () => of(null) };
        const voiceService: any = { voiceModeStatus$: () => of({ running: false }) };
        const voicePlaybackState: any = { state$: of({ stage: 'idle', messageId: null }), refresh: () => undefined };
        return TestBed.runInInjectionContext(() => new ChatComponent(
            {} as any,
            authService,
            configService,
            {} as any,
            {} as any,
            voiceService,
            voicePlaybackState,
            websocketService,
            { open: () => undefined } as any,
            new ChatRunStoreService(),
            new ChatMessageStoreService(),
            new ChatSessionStateService(),
        ));
    }

    it('shows every source when the event asks for it', () => {
        const component = create();

        component.onSourceFilterChanged(new CustomEvent('chat-history-source-filter-changed', {
            detail: { showAllSources: true },
        }));

        expect(component.showAllChatSources).toBeTrue();
    });

    it('turns every-source mode off when the event carries no detail', () => {
        const component = create();
        component.showAllChatSources = true;

        component.onSourceFilterChanged(new Event('chat-history-source-filter-changed'));

        expect(component.showAllChatSources).toBeFalse();
    });
});
