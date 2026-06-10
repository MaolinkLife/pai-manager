/**
 * Compliance pipeline mappers (0.9.0 Wave 2).
 *
 * Each compliance check (Validator §3.5, Language guard §3.5-bis,
 * Confidence §3.8, Factuality §3.9, Self-Watcher §3.7) lives at the
 * top level of the project config because they wire into
 * conversation.generate_standard rather than under any existing domain.
 * They share a similar shape (enabled flag + threshold + a few tuning
 * numbers) but the field names differ, so each has its own mapper.
 */

import {
    ConfidenceConfigDto,
    FactualityConfigDto,
    LanguageGuardConfigDto,
    SelfWatcherConfigDto,
    ValidatorConfigDto,
} from '../models/project-config.dto';
import {
    ConfidenceConfig,
    FactualityConfig,
    LanguageGuardConfig,
    SelfWatcherConfig,
    ValidatorConfig,
} from '../models/project-config.model';

// ---- Validator -----------------------------------------------------------

export const mapValidatorDtoToModel = (
    dto?: ValidatorConfigDto,
): ValidatorConfig => ({
    enabled: dto?.enabled ?? false,
    threshold: dto?.threshold ?? 0.7,
    maxTokens: dto?.max_tokens ?? 256,
    temperature: dto?.temperature ?? 0.0,
    instructionCharLimit: dto?.instruction_char_limit ?? 4000,
    outputCharLimit: dto?.output_char_limit ?? 4000,
});

export const mapValidatorModelToDto = (
    model?: ValidatorConfig,
): ValidatorConfigDto => ({
    enabled: model?.enabled ?? false,
    threshold: model?.threshold ?? 0.7,
    max_tokens: model?.maxTokens ?? 256,
    temperature: model?.temperature ?? 0.0,
    instruction_char_limit: model?.instructionCharLimit ?? 4000,
    output_char_limit: model?.outputCharLimit ?? 4000,
});

// ---- Language guard ------------------------------------------------------

export const mapLanguageGuardDtoToModel = (
    dto?: LanguageGuardConfigDto,
): LanguageGuardConfig => ({
    enabled: dto?.enabled ?? false,
    minDominance: dto?.min_dominance ?? 0.7,
    minOutputChars: dto?.min_output_chars ?? 40,
});

export const mapLanguageGuardModelToDto = (
    model?: LanguageGuardConfig,
): LanguageGuardConfigDto => ({
    enabled: model?.enabled ?? false,
    min_dominance: model?.minDominance ?? 0.7,
    min_output_chars: model?.minOutputChars ?? 40,
});

// ---- Confidence ----------------------------------------------------------

export const mapConfidenceDtoToModel = (
    dto?: ConfidenceConfigDto,
): ConfidenceConfig => ({
    enabled: dto?.enabled ?? false,
    threshold: dto?.threshold ?? 0.5,
    maxTokens: dto?.max_tokens ?? 64,
    temperature: dto?.temperature ?? 0.0,
    userCharLimit: dto?.user_char_limit ?? 2000,
    outputCharLimit: dto?.output_char_limit ?? 4000,
});

export const mapConfidenceModelToDto = (
    model?: ConfidenceConfig,
): ConfidenceConfigDto => ({
    enabled: model?.enabled ?? false,
    threshold: model?.threshold ?? 0.5,
    max_tokens: model?.maxTokens ?? 64,
    temperature: model?.temperature ?? 0.0,
    user_char_limit: model?.userCharLimit ?? 2000,
    output_char_limit: model?.outputCharLimit ?? 4000,
});

// ---- Factuality ----------------------------------------------------------

export const mapFactualityDtoToModel = (
    dto?: FactualityConfigDto,
): FactualityConfig => ({
    enabled: dto?.enabled ?? false,
    gateOnLowConfidence: dto?.gate_on_low_confidence ?? true,
    topK: dto?.top_k ?? 3,
    minSimilarity: dto?.min_similarity ?? 0.6,
    maxClaims: dto?.max_claims ?? 6,
    claimMinLength: dto?.claim_min_length ?? 3,
});

export const mapFactualityModelToDto = (
    model?: FactualityConfig,
): FactualityConfigDto => ({
    enabled: model?.enabled ?? false,
    gate_on_low_confidence: model?.gateOnLowConfidence ?? true,
    top_k: model?.topK ?? 3,
    min_similarity: model?.minSimilarity ?? 0.6,
    max_claims: model?.maxClaims ?? 6,
    claim_min_length: model?.claimMinLength ?? 3,
});

// ---- Self-Watcher --------------------------------------------------------

export const mapSelfWatcherDtoToModel = (
    dto?: SelfWatcherConfigDto,
): SelfWatcherConfig => ({
    enabled: dto?.enabled ?? false,
    mismatchThreshold: dto?.mismatch_threshold ?? 0.5,
    nightlyReflectionEnabled: dto?.nightly_reflection_enabled ?? true,
    lookbackDays: dto?.lookback_days ?? 7,
    maxEventsInCluster: dto?.max_events_in_cluster ?? 20,
    llmMaxTokens: dto?.llm_max_tokens ?? 220,
    llmTemperature: dto?.llm_temperature ?? 0.5,
});

export const mapSelfWatcherModelToDto = (
    model?: SelfWatcherConfig,
): SelfWatcherConfigDto => ({
    enabled: model?.enabled ?? false,
    mismatch_threshold: model?.mismatchThreshold ?? 0.5,
    nightly_reflection_enabled: model?.nightlyReflectionEnabled ?? true,
    lookback_days: model?.lookbackDays ?? 7,
    max_events_in_cluster: model?.maxEventsInCluster ?? 20,
    llm_max_tokens: model?.llmMaxTokens ?? 220,
    llm_temperature: model?.llmTemperature ?? 0.5,
});
