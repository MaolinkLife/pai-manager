import { Message } from '../../../core/models/message.model';
import { RuntimeState } from './chat-runtime.model';

export interface RuntimeStageView {
    id: string;
    label: string;
    state: 'pending' | 'active' | 'done';
    elapsedMs?: number;
    metaText?: string;
}

export interface UsageDetailLine {
    key: string;
    value: string;
}

const RUNTIME_STAGE_GROUPS: Array<{ id: string; label: string; keys: string[]; optional?: boolean }> = [
    { id: 'analysis', label: 'Провожу анализ', keys: ['analysis'] },
    { id: 'queue', label: 'Планирую модули', keys: ['queue'], optional: true },
    { id: 'memory', label: 'Ищу в памяти', keys: ['memory'] },
    { id: 'instructions', label: 'Собираю инструкции', keys: ['decision', 'moral', 'prompt'] },
    { id: 'vision', label: 'Обрабатываю медиа', keys: ['vision'], optional: true },
    { id: 'image_prompt', label: 'Готовлю промпт картинки', keys: ['image_prompt'], optional: true },
    { id: 'image_generation', label: 'Генерирую изображение', keys: ['image_generation'], optional: true },
    { id: 'image_vision', label: 'Проверяю изображение', keys: ['image_vision'], optional: true },
    { id: 'reasoning', label: 'Размышляю', keys: ['reasoning'], optional: true },
    { id: 'answer', label: 'Печатаю ответ', keys: ['answer'], optional: true },
    { id: 'generation', label: 'Вызов модели', keys: ['generation'] },
];

export function getRuntimeSummary(runtime: RuntimeState, provider?: string): string {
    const status = runtime.status === 'completed'
        ? 'готово'
        : runtime.status === 'stopped'
            ? 'остановлено'
            : runtime.status === 'error'
                ? 'ошибка'
                : runtime.status === 'queued'
                    ? 'ожидает'
                    : runtime.status === 'stopping'
                        ? 'останавливаю...'
                        : 'в процессе';
    const model = runtime.model || provider || 'provider';
    if (typeof runtime.elapsedMs === 'number') {
        const seconds = Math.max(0, Math.round(runtime.elapsedMs / 10) / 100);
        return `${model} • ${status} • ${seconds}s`;
    }
    return `${model} • ${status}`;
}

export function getRuntimeStages(runtime: RuntimeState): RuntimeStageView[] {
    const traces = runtime.traces || [];
    return RUNTIME_STAGE_GROUPS
        .map((group) => {
            const related = traces.filter((trace) => group.keys.includes(trace.stage));
            const hasStart = related.some((trace) => trace.state === 'start');
            const hasEnd = related.some((trace) => trace.state === 'end');
            const hasError = related.some((trace) => trace.state === 'error');
            const endTrace = related.find((trace) => trace.state === 'end' && typeof trace.elapsedMs === 'number');
            const detailTrace = [...related].reverse().find((trace) => !!trace.details);
            const state: RuntimeStageView['state'] = hasEnd ? 'done' : ((hasStart || hasError) ? 'active' : 'pending');
            return {
                id: group.id,
                label: group.label,
                state,
                elapsedMs: endTrace?.elapsedMs,
                metaText: formatRuntimeTraceMeta(detailTrace?.details),
            };
        })
        .filter((stage) => {
            const meta = RUNTIME_STAGE_GROUPS.find((group) => group.id === stage.id);
            return !meta?.optional || stage.state !== 'pending';
        });
}

export function getRuntimeActiveLabel(runtime?: RuntimeState): string {
    if (!runtime) {
        return 'Обрабатываю запрос';
    }
    const active = getRuntimeStages(runtime).find((stage) => stage.state === 'active');
    if (active) {
        return active.label;
    }
    if (runtime.status === 'completed') {
        return 'Ответ готов';
    }
    if (runtime.status === 'queued') {
        return 'Ожидает очереди';
    }
    if (runtime.status === 'stopped') {
        return 'Генерация остановлена';
    }
    if (runtime.status === 'error') {
        return 'Ошибка генерации';
    }
    return 'Обрабатываю запрос';
}

export function getUsageDetailLines(msg: Message): UsageDetailLine[] {
    const usage = msg.runtime?.usage || {};
    const meta = msg.runtime?.meta || {};
    const lines: UsageDetailLine[] = [];
    const preferred = [
        'prompt_eval_count',
        'eval_count',
        'total_duration',
        'load_duration',
        'prompt_eval_duration',
        'eval_duration',
        'prompt_tokens',
        'completion_tokens',
        'total_tokens',
    ];

    const pushLine = (key: string, value: any): void => {
        if (value === undefined || value === null || value === '') {
            return;
        }
        lines.push({ key, value: formatUsageValue(key, value) });
    };

    preferred.forEach((key) => pushLine(key, usage[key]));
    Object.entries(usage).forEach(([key, value]) => {
        if (!preferred.includes(key)) {
            pushLine(key, value);
        }
    });
    pushLine('reasoning_elapsed', msg.runtime?.reasoningElapsedMs);
    pushLine('answer_elapsed', msg.runtime?.answerElapsedMs);
    Object.entries(meta).forEach(([key, value]) => pushLine(`meta.${key}`, value));
    return lines;
}

function formatRuntimeTraceMeta(details?: Record<string, any>): string | undefined {
    if (!details || typeof details !== 'object') {
        return undefined;
    }
    const usage = details['usage'] && typeof details['usage'] === 'object' ? details['usage'] : {};
    const tokens = usage['total_tokens']
        ?? usage['eval_count']
        ?? usage['completion_tokens']
        ?? usage['response_tokens'];
    const parts: string[] = [];
    if (tokens !== undefined && tokens !== null && tokens !== '') {
        parts.push(`${tokens} tok`);
    }
    const promptTokens = usage['prompt_tokens'] ?? usage['prompt_eval_count'];
    if (promptTokens !== undefined && promptTokens !== null && promptTokens !== '') {
        parts.push(`${promptTokens} in`);
    }
    if (details['model']) {
        parts.push(String(details['model']));
    } else if (details['provider']) {
        parts.push(String(details['provider']));
    }
    if (details['bytes']) {
        const mb = Number(details['bytes']) / (1024 * 1024);
        parts.push(`${mb >= 0.1 ? mb.toFixed(1) + ' MB' : details['bytes'] + ' B'}`);
    }
    if (details['description_length']) {
        parts.push(`${details['description_length']} chars`);
    }
    return parts.length ? parts.join(' • ') : undefined;
}

function formatUsageValue(key: string, value: any): string {
    if (typeof value === 'object') {
        return JSON.stringify(value);
    }
    const numeric = Number(value);
    if (Number.isFinite(numeric) && key.endsWith('_duration')) {
        if (numeric > 1000000) {
            return `${Math.round(numeric / 10000000) / 100}s`;
        }
        return `${Math.round(numeric / 10) / 100}ms`;
    }
    if (Number.isFinite(numeric) && key.endsWith('_elapsed')) {
        return numeric >= 1000
            ? `${Math.round(numeric / 10) / 100}s`
            : `${Math.round(numeric * 100) / 100}ms`;
    }
    return String(value);
}
