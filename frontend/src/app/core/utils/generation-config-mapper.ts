import { ProjectConfig } from '../models/project-config.model';

const DEFAULT_GENERATION = {
    temperature: 0.85,
    minP: 0.05,
    topP: 0.9,
    topK: 50,
    repeatPenalty: 1.2,
    stop: null,
    numPredict: 2048,
    normalizeMessages: false,
    name: 'Default',
    description: 'Basic generation parameters',
};

const numberFrom = (value: any, fallback: number): number => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

export const mapGenerationDtoToModel = (dto: any) => ({
    temperature: numberFrom(dto?.temperature, DEFAULT_GENERATION.temperature),
    minP: numberFrom(dto?.min_p ?? dto?.minP, DEFAULT_GENERATION.minP),
    topP: numberFrom(dto?.top_p ?? dto?.topP, DEFAULT_GENERATION.topP),
    topK: numberFrom(dto?.top_k ?? dto?.topK, DEFAULT_GENERATION.topK),
    repeatPenalty: numberFrom(
        dto?.repeat_penalty ?? dto?.repeatPenalty,
        DEFAULT_GENERATION.repeatPenalty
    ),
    stop: dto?.stop ?? DEFAULT_GENERATION.stop,
    numPredict: numberFrom(
        dto?.num_predict ?? dto?.numPredict,
        DEFAULT_GENERATION.numPredict
    ),
    normalizeMessages: Boolean(
        dto?.normalize_messages ?? dto?.normalizeMessages ?? DEFAULT_GENERATION.normalizeMessages
    ),
    name: dto?.name ?? DEFAULT_GENERATION.name,
    description: dto?.description ?? DEFAULT_GENERATION.description,
});

export const mapGenerationModelToDto = (generation: ProjectConfig['generateSettings']) => ({
    temperature: numberFrom(generation?.temperature, DEFAULT_GENERATION.temperature),
    min_p: numberFrom(generation?.minP, DEFAULT_GENERATION.minP),
    top_p: numberFrom(generation?.topP, DEFAULT_GENERATION.topP),
    top_k: numberFrom(generation?.topK, DEFAULT_GENERATION.topK),
    repeat_penalty: numberFrom(
        generation?.repeatPenalty,
        DEFAULT_GENERATION.repeatPenalty
    ),
    stop: generation?.stop ?? DEFAULT_GENERATION.stop,
    num_predict: numberFrom(generation?.numPredict, DEFAULT_GENERATION.numPredict),
    normalize_messages: Boolean(generation?.normalizeMessages ?? DEFAULT_GENERATION.normalizeMessages),
    name: generation?.name ?? DEFAULT_GENERATION.name,
    description: generation?.description ?? DEFAULT_GENERATION.description,
});
