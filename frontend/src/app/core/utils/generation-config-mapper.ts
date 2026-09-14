import { ProjectConfigDto } from '../models/project-config.dto';
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

/** A settings save sends only the fields it carries — nothing is filled with defaults. */
export const mapGenerationModelToDto = (
    generation: Partial<ProjectConfig['generateSettings']> | undefined
): ProjectConfigDto['generate_settings'] => {
    const dto: Record<string, any> = {};
    if (!generation) {
        return dto as ProjectConfigDto['generate_settings'];
    }
    const numbers: Array<[string, unknown]> = [
        ['temperature', generation.temperature],
        ['min_p', generation.minP],
        ['top_p', generation.topP],
        ['top_k', generation.topK],
        ['repeat_penalty', generation.repeatPenalty],
        ['num_predict', generation.numPredict],
    ];
    numbers.forEach(([key, value]) => {
        const parsed = Number(value);
        if (value !== undefined && value !== null && Number.isFinite(parsed)) {
            dto[key] = parsed;
        }
    });
    if (generation.stop !== undefined) {
        dto['stop'] = generation.stop;
    }
    if (generation.normalizeMessages !== undefined) {
        dto['normalize_messages'] = Boolean(generation.normalizeMessages);
    }
    if (generation.name !== undefined) {
        dto['name'] = generation.name;
    }
    if (generation.description !== undefined) {
        dto['description'] = generation.description;
    }
    return dto as ProjectConfigDto['generate_settings'];
};
