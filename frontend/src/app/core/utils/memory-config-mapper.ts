import {
    MemoryConfigDto,
    MemoryConsolidationConfigDto,
    MemoryConsolidationJudgeDto,
    MemoryDiaryConfigDto,
    MemoryDiaryNarrativeConfigDto,
} from '../models/project-config.dto';
import {
    MemoryConfig,
    MemoryConsolidationConfig,
    MemoryConsolidationJudgeConfig,
    MemoryDiaryConfig,
    MemoryDiaryNarrativeConfig,
} from '../models/project-config.model';

const mapJudgeDtoToModel = (
    dto?: MemoryConsolidationJudgeDto,
): MemoryConsolidationJudgeConfig => ({
    enabled: dto?.enabled ?? false,
    provider: dto?.provider ?? 'ollama',
    model: dto?.model ?? '',
    temperature: dto?.temperature ?? 0.0,
    maxTokens: dto?.max_tokens ?? 512,
    requestTimeout: dto?.request_timeout ?? 60,
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
    };
};

const mapDiaryModelToDto = (model?: MemoryDiaryConfig): MemoryDiaryConfigDto | undefined => {
    if (!model) {
        return undefined;
    }
    return {
        narrative: mapNarrativeModelToDto(model.narrative),
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
    diary: mapDiaryDtoToModel(dto?.diary),
});

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
    const diaryDto = mapDiaryModelToDto(model?.diary);
    if (diaryDto) {
        dto.diary = diaryDto;
    }
    return dto;
};
