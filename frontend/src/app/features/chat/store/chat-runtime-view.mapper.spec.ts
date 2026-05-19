import { Message } from '../../../core/models/message.model';
import { RuntimeState } from './chat-runtime.model';
import { getRuntimeActiveLabel, getRuntimeStages, getRuntimeSummary, getUsageDetailLines } from './chat-runtime-view.mapper';

describe('chat runtime view mapper', () => {
    it('groups raw runtime traces into stable UI stages', () => {
        const runtime = runtimeState({
            traces: [
                { stage: 'analysis', state: 'end', elapsedMs: 10 },
                { stage: 'reasoning', state: 'start' },
                { stage: 'generation', state: 'end', elapsedMs: 40, details: { model: 'qwen', usage: { eval_count: 12 } } },
            ],
        });

        const stages = getRuntimeStages(runtime);

        expect(stages.find((stage) => stage.id === 'analysis')?.state).toBe('done');
        expect(stages.find((stage) => stage.id === 'reasoning')?.state).toBe('active');
        expect(stages.find((stage) => stage.id === 'generation')?.metaText).toContain('12 tok');
        expect(getRuntimeActiveLabel(runtime)).toBe('Размышляю');
    });

    it('formats runtime summary and usage details', () => {
        const message = messageWithRuntime({
            status: 'completed',
            elapsedMs: 12345,
            model: 'ollama/qwen',
            usage: { prompt_eval_count: 10, eval_count: 20 },
            reasoningElapsedMs: 1500,
            answerElapsedMs: 250,
        });

        expect(getRuntimeSummary(message.runtime!, message.provider)).toBe('ollama/qwen • готово • 12.35s');
        expect(getUsageDetailLines(message).map((line) => line.key)).toContain('reasoning_elapsed');
        expect(getUsageDetailLines(message).find((line) => line.key === 'answer_elapsed')?.value).toBe('250ms');
    });
});

function runtimeState(partial: Partial<RuntimeState>): RuntimeState {
    return {
        runId: 'run-1',
        status: 'running',
        traces: [],
        usage: null,
        meta: null,
        ...partial,
    };
}

function messageWithRuntime(runtime: Partial<RuntimeState>): Message {
    return {
        id: 'm1',
        role: 'assistant',
        content: 'hello',
        timestamp: new Date(0).toISOString(),
        provider: 'provider',
        runtime: runtimeState(runtime),
    };
}
