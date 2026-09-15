import { Message } from '../../../core/models/message.model';
import { ChatMessageStoreService } from './chat-message-store.service';

describe('ChatMessageStoreService', () => {
    let store: ChatMessageStoreService;

    beforeEach(() => {
        store = new ChatMessageStoreService();
    });

    it('buffers streaming chunks until the next render flush', () => {
        store.startStreaming(message({ id: 'tmp-1', role: 'assistant', content: '' }));

        store.appendStreamingContent('one ');
        store.appendStreamingContent('two');

        expect(store.currentStreamingMessage?.content).toBe('');

        store.flushPendingStream();

        expect(store.currentStreamingMessage?.content).toBe('one two');
        expect(store.messages[0].content).toBe('one two');
    });

    it('replaces temp ids while preserving the active streaming pointer', () => {
        store.startStreaming(message({ id: 'tmp-1', role: 'assistant', content: 'draft' }));

        store.replaceTempId('tmp-1', 'real-1', { isPending: false });

        expect(store.currentStreamingMessage?.id).toBe('real-1');
        expect(store.currentStreamingMessage?.isPending).toBeFalse();
    });

    it('keeps a sent message the server has not saved yet when the history is reloaded', () => {
        store.setHistory([message({ id: 'u1', role: 'user', content: 'saved' })]);
        store.push(message({ id: 'temp-2', role: 'user', content: 'not saved yet', isPending: true }));

        store.setHistory([
            message({ id: 'u1', role: 'user', content: 'saved' }),
            message({ id: 'a1', role: 'assistant', content: 'reply' }),
        ]);

        expect(store.messages.map((item) => item.id)).toEqual(['u1', 'a1', 'temp-2']);
    });

    it('drops a half-streamed reply when the history is reloaded', () => {
        store.startStreaming(message({ id: 'tmp-a', role: 'assistant', content: 'part', isPending: true }));

        store.setHistory([message({ id: 'u1', role: 'user', content: 'hello' })]);

        expect(store.messages.map((item) => item.id)).toEqual(['u1']);
        expect(store.currentStreamingMessage).toBeNull();
    });

    it('drops a temporary message whose saved copy is already shown instead of doubling it', () => {
        store.setHistory([message({ id: 'real-1', role: 'user', content: 'hi' })]);
        store.push(message({ id: 'temp-1', role: 'user', content: 'hi', isPending: true }));

        store.replaceTempId('temp-1', 'real-1', { isPending: false });

        expect(store.messages.map((item) => item.id)).toEqual(['real-1']);
    });

    it('removes chained assistant response after deleted user message', () => {
        store.setHistory([
            message({ id: 'u1', role: 'user', content: 'hello' }),
            message({ id: 'a1', role: 'assistant', content: 'hi' }),
            message({ id: 'u2', role: 'user', content: 'next' }),
        ]);

        store.deleteMessage('u1', true);

        expect(store.messages.map((item) => item.id)).toEqual(['u2']);
    });
});

function message(partial: Partial<Message>): Message {
    return {
        id: partial.id || 'm1',
        role: partial.role || 'assistant',
        content: partial.content || '',
        timestamp: partial.timestamp || new Date(0).toISOString(),
        isPending: partial.isPending,
        media: partial.media,
        runId: partial.runId,
        provider: partial.provider,
        reasoning: partial.reasoning,
        stopped: partial.stopped,
        source: partial.source,
        runtime: partial.runtime,
    };
}
