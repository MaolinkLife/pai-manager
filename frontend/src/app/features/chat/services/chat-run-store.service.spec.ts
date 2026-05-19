import { ChatRunStoreService } from './chat-run-store.service';

describe('ChatRunStoreService', () => {
    let store: ChatRunStoreService;

    beforeEach(() => {
        store = new ChatRunStoreService();
    });

    it('normalizes runtime trace aliases into stable UI stages', () => {
        const trace = store.normalizeRuntimeTrace({
            stage: 'media',
            status: 'completed',
            elapsed_ms: 42,
            details: {
                provider: 'ollama',
                secret: 'must not leak',
            },
        });

        expect(trace.stage).toBe('vision');
        expect(trace.state).toBe('end');
        expect(trace.elapsedMs).toBe(42);
        expect(trace.details).toEqual({ provider: 'ollama' });
    });

    it('deduplicates identical adjacent traces', () => {
        const trace = store.normalizeRuntimeTrace({ stage: 'reasoning', status: 'running' });

        const first = store.pushRuntimeTrace('run-1', trace);
        const second = store.pushRuntimeTrace('run-1', trace);

        expect(first?.traces.length).toBe(1);
        expect(second?.traces.length).toBe(1);
    });
});
