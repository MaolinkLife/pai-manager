import {
    MemoryConfigDto,
    MemoryConsolidationConfigDto,
    MemoryConsolidationJudgeDto,
    MemoryDiaryConfigDto,
    MemoryDiaryNarrativeConfigDto,
    MemoryShortTermConfigDto,
} from '../models/project-config.dto';
import {
    MemoryConfig,
    MemoryConsolidationConfig,
    MemoryConsolidationJudgeConfig,
    MemoryDiaryConfig,
    MemoryDiaryNarrativeConfig,
    MemoryShortTermConfig,
} from '../models/project-config.model';
import { promptField } from './technical-prompt-field';

const mapJudgeDtoToModel = (
    dto?: MemoryConsolidationJudgeDto,
): MemoryConsolidationJudgeConfig => ({
    enabled: dto?.enabled ?? false,
    provider: dto?.provider ?? 'ollama',
    model: dto?.model ?? '',
    temperature: dto?.temperature ?? 0.0,
    maxTokens: dto?.max_tokens ?? 512,
    requestTimeout: dto?.request_timeout ?? 60,
    systemPrompt: dto?.system_prompt ?? '',
});

const mapJudgeModelToDto = (
    model?: MemoryConsolidationJudgeConfig,
): MemoryConsolidationJudgeDto => ({
    enabled: model?.enabled ?? false,
    provider: model?.provider ?? 'ollama',
    model: model?.model ?? '',
    temperature: model?.temperature ?? 0.0,
    max_tokens: model?.maxTokens ?? 512,
    request_timeout: model?.requestTimeout ?? 60,
    ...promptField('system_prompt', model?.systemPrompt),
});

const mapConsolidationDtoToModel = (
    dto?: MemoryConsolidationConfigDto,
): MemoryConsolidationConfig | undefined => {
    if (!dto) {
        return undefined;
    }
    return {
        importanceThreshold: dto.importance_threshold ?? 0.2,
        judge: mapJudgeDtoToModel(dto.judge),
    };
};

const mapConsolidationModelToDto = (
    model?: MemoryConsolidationConfig,
): MemoryConsolidationConfigDto | undefined => {
    if (!model) {
        return undefined;
    }
    return {
        importance_threshold: model.importanceThreshold,
        judge: mapJudgeModelToDto(model.judge),
    };
};

const mapShortTermDtoToModel = (dto?: MemoryShortTermConfigDto): MemoryShortTermConfig | undefined => {
    if (!dto) {
        return undefined;
    }
    return {
        startupRefreshEnabled: dto.startup_refresh_enabled ?? false,
        summarySystemPrompt: dto.summary_system_prompt ?? '',
        summaryTaskPrompt: dto.summary_task_prompt ?? '',
    };
};

const mapShortTermModelToDto = (model?: MemoryShortTermConfig): MemoryShortTermConfigDto | undefined => {
    if (!model) {
        return undefined;
    }
    return {
        ...(model.startupRefreshEnabled === undefined ? {} : { startup_refresh_enabled: model.startupRefreshEnabled }),
        ...promptField('summary_system_prompt', model.summarySystemPrompt),
        ...promptField('summary_task_prompt', model.summaryTaskPrompt),
    };
};

const mapNarrativeDtoToModel = (
    dto?: MemoryDiaryNarrativeConfigDto,
): MemoryDiaryNarrativeConfig => ({
    enabled: dto?.enabled ?? true,
    minChars: dto?.min_chars ?? 80,
    maxChars: dto?.max_chars ?? 3000,
});

const mapNarrativeModelToDto = (
    model?: MemoryDiaryNarrativeConfig,
): MemoryDiaryNarrativeConfigDto => ({
    enabled: model?.enabled ?? true,
    min_chars: model?.minChars ?? 80,
    max_chars: model?.maxChars ?? 3000,
});

const mapDiaryDtoToModel = (dto?: MemoryDiaryConfigDto): MemoryDiaryConfig | undefined => {
    if (!dto) {
        return undefined;
    }
    return {
        narrative: mapNarrativeDtoToModel(dto.narrative),
        systemPrompt: dto.system_prompt ?? '',
        userTemplate: dto.user_template ?? '',
    };
};

const mapDiaryModelToDto = (model?: MemoryDiaryConfig): MemoryDiaryConfigDto | undefined => {
    if (!model) {
        return undefined;
    }
    return {
        narrative: mapNarrativeModelToDto(model.narrative),
        ...promptField('system_prompt', model.systemPrompt),
        ...promptField('user_template', model.userTemplate),
    };
};

export const mapMemoryDtoToModel = (dto: MemoryConfigDto | undefined): MemoryConfig => ({
    deepMemoryEnabled: dto?.deep_memory_enabled ?? true,
    recentLimit: dto?.recent_limit ?? 32,
    similarityThreshold: dto?.similarity_threshold ?? 0.7,
    sessionWindow: dto?.session_window ?? 'day',
    sessionEnabled: dto?.session_enabled ?? true,
    embeddingProvider: dto?.embedding_provider ?? 'auto',
    embeddingModel: dto?.embedding_model ?? 'nomic-embed-text',
    consolidation: mapConsolidationDtoToModel(dto?.consolidation),
    shortTerm: mapShortTermDtoToModel(dto?.short_term),
    diary: mapDiaryDtoToModel(dto?.diary),
});

const putDefined = (target: Record<string, any>, key: string, value: unknown): void => {
    if (value !== undefined) {
        target[key] = value;
    }
};

/**
 * A settings save sends only the fields it carries. Filling the base memory fields
 * with frontend defaults overwrote recent_limit, the embedding model and the rest on
 * every save of the memory sections (found 2026-09-13).
 */
export const mapMemoryPartialModelToDto = (
    model: Partial<MemoryConfig> | undefined,
): Partial<MemoryConfigDto> => {
    const dto: Record<string, any> = {};
    if (!model) {
        return dto;
    }
    putDefined(dto, 'deep_memory_enabled', model.deepMemoryEnabled);
    putDefined(dto, 'recent_limit', model.recentLimit);
    putDefined(dto, 'similarity_threshold', model.similarityThreshold);
    putDefined(dto, 'session_window', model.sessionWindow);
    putDefined(dto, 'session_enabled', model.sessionEnabled);
    putDefined(dto, 'embedding_provider', model.embeddingProvider);
    putDefined(dto, 'embedding_model', model.embeddingModel);

    if (model.consolidation) {
        const consolidation: Record<string, any> = {};
        putDefined(consolidation, 'importance_threshold', model.consolidation.importanceThreshold);
        const judge = model.consolidation.judge;
        if (judge) {
            const judgeDto: Record<string, any> = {};
            putDefined(judgeDto, 'enabled', judge.enabled);
            putDefined(judgeDto, 'provider', judge.provider);
            putDefined(judgeDto, 'model', judge.model);
            putDefined(judgeDto, 'temperature', judge.temperature);
            putDefined(judgeDto, 'max_tokens', judge.maxTokens);
            putDefined(judgeDto, 'request_timeout', judge.requestTimeout);
            Object.assign(judgeDto, promptField('system_prompt', judge.systemPrompt));
            consolidation['judge'] = judgeDto;
        }
        dto['consolidation'] = consolidation;
    }

    const shortTermDto = mapShortTermModelToDto(model.shortTerm);
    if (shortTermDto) {
        dto['short_term'] = shortTermDto;
    }

    if (model.diary) {
        const diary: Record<string, any> = {};
        const narrative = model.diary.narrative;
        if (narrative) {
            const narrativeDto: Record<string, any> = {};
            putDefined(narrativeDto, 'enabled', narrative.enabled);
            putDefined(narrativeDto, 'min_chars', narrative.minChars);
            putDefined(narrativeDto, 'max_chars', narrative.maxChars);
            diary['narrative'] = narrativeDto;
        }
        Object.assign(diary, promptField('system_prompt', model.diary.systemPrompt));
        Object.assign(diary, promptField('user_template', model.diary.userTemplate));
        dto['diary'] = diary;
    }

    return dto as Partial<MemoryConfigDto>;
};

export const mapMemoryModelToDto = (model: MemoryConfig | undefined): MemoryConfigDto => {
    const dto: MemoryConfigDto = {
        deep_memory_enabled: model?.deepMemoryEnabled ?? true,
        recent_limit: model?.recentLimit ?? 32,
        similarity_threshold: model?.similarityThreshold ?? 0.7,
        session_window: model?.sessionWindow ?? 'day',
        session_enabled: model?.sessionEnabled ?? true,
        embedding_provider: model?.embeddingProvider ?? 'auto',
        embedding_model: model?.embeddingModel ?? 'nomic-embed-text',
    };
    const consolidationDto = mapConsolidationModelToDto(model?.consolidation);
    if (consolidationDto) {
        dto.consolidation = consolidationDto;
    }
    const shortTermDto = mapShortTermModelToDto(model?.shortTerm);
    if (shortTermDto) {
        dto.short_term = shortTermDto;
    }
    const diaryDto = mapDiaryModelToDto(model?.diary);
    if (diaryDto) {
        dto.diary = diaryDto;
    }
    return dto;
};
