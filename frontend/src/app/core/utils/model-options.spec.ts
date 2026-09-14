import { ModelIndexEntry } from '../services/api.service';
import { buildModelOptions, ModelOptionLabels, modelNamesWith } from './model-options';

const entry = (name: string, capabilities: string[]): ModelIndexEntry => ({
    provider: 'ollama',
    name,
    capabilities,
    declared: capabilities,
    declared_known: true,
    owner_marked: false,
    differs: false,
});

const INDEX = [
    entry('qwen3.5:9b', ['completion', 'vision', 'tools']),
    entry('gpt-oss:20b', ['completion', 'thinking', 'tools']),
    entry('nomic-embed-text:latest', ['embedding']),
];

const LABELS: ModelOptionLabels = {
    noModels: 'no models',
    notMarked: 'no mark',
    notIndexed: 'not in the index',
    capability: 'vision',
};

describe('model pickers by the model index', () => {
    it('offers only the models that can do the capability', () => {
        expect(buildModelOptions(INDEX, 'vision', 'qwen3.5:9b', LABELS)).toEqual([
            { value: 'qwen3.5:9b', label: 'qwen3.5:9b' },
        ]);
        expect(buildModelOptions(INDEX, 'completion', '', LABELS).map((option) => option.value)).toEqual([
            'qwen3.5:9b',
            'gpt-oss:20b',
        ]);
    });

    it('keeps the chosen model without the mark, noted, first', () => {
        expect(buildModelOptions(INDEX, 'vision', 'gpt-oss:20b', LABELS)).toEqual([
            { value: 'gpt-oss:20b', label: 'gpt-oss:20b — no mark: vision' },
            { value: 'qwen3.5:9b', label: 'qwen3.5:9b' },
        ]);
    });

    it('notes a chosen model the index does not know', () => {
        expect(buildModelOptions(INDEX, 'vision', 'llava:latest', LABELS)[0]).toEqual({
            value: 'llava:latest',
            label: 'llava:latest — not in the index',
        });
    });

    it('says there are no models, or stays empty when asked to', () => {
        expect(buildModelOptions([], 'vision', '', LABELS)).toEqual([{ value: '', label: 'no models', disabled: true }]);
        expect(buildModelOptions(null, 'vision', '', LABELS, { placeholderWhenEmpty: false })).toEqual([]);
    });

    it('lists plain names by capability', () => {
        expect(modelNamesWith(INDEX, 'vision')).toEqual(['qwen3.5:9b']);
        expect(modelNamesWith(null, 'vision')).toEqual([]);
    });
});
