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
import { promptField } from './technical-prompt-field';

/** A settings save sends only the fields it carries — nothing is filled with defaults. */
const definedFields = (pairs: Array<[string, unknown]>): Record<string, unknown> =>
    pairs.reduce((dto: Record<string, unknown>, [key, value]) => {
        if (value !== undefined) {
            dto[key] = value;
        }
        return dto;
    }, {});

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
    systemPrompt: dto?.system_prompt ?? '',
});

export const mapValidatorModelToDto = (
    model?: Partial<ValidatorConfig>,
): ValidatorConfigDto => ({
    ...definedFields([
        ['enabled', model?.enabled],
        ['threshold', model?.threshold],
        ['max_tokens', model?.maxTokens],
        ['temperature', model?.temperature],
        ['instruction_char_limit', model?.instructionCharLimit],
        ['output_char_limit', model?.outputCharLimit],
    ]),
    ...promptField('system_prompt', model?.systemPrompt),
}) as ValidatorConfigDto;

// ---- Language guard ------------------------------------------------------

export const mapLanguageGuardDtoToModel = (
    dto?: LanguageGuardConfigDto,
): LanguageGuardConfig => ({
    enabled: dto?.enabled ?? false,
    minDominance: dto?.min_dominance ?? 0.7,
    minOutputChars: dto?.min_output_chars ?? 40,
});

export const mapLanguageGuardModelToDto = (
    model?: Partial<LanguageGuardConfig>,
): LanguageGuardConfigDto => definedFields([
    ['enabled', model?.enabled],
    ['min_dominance', model?.minDominance],
    ['min_output_chars', model?.minOutputChars],
]) as LanguageGuardConfigDto;

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
    systemPrompt: dto?.system_prompt ?? '',
});

export const mapConfidenceModelToDto = (
    model?: Partial<ConfidenceConfig>,
): ConfidenceConfigDto => ({
    ...definedFields([
        ['enabled', model?.enabled],
        ['threshold', model?.threshold],
        ['max_tokens', model?.maxTokens],
        ['temperature', model?.temperature],
        ['user_char_limit', model?.userCharLimit],
        ['output_char_limit', model?.outputCharLimit],
    ]),
    ...promptField('system_prompt', model?.systemPrompt),
}) as ConfidenceConfigDto;

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
    model?: Partial<FactualityConfig>,
): FactualityConfigDto => definedFields([
    ['enabled', model?.enabled],
    ['gate_on_low_confidence', model?.gateOnLowConfidence],
    ['top_k', model?.topK],
    ['min_similarity', model?.minSimilarity],
    ['max_claims', model?.maxClaims],
    ['claim_min_length', model?.claimMinLength],
]) as FactualityConfigDto;

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
    reflectionPrompt: dto?.reflection_prompt ?? '',
});

export const mapSelfWatcherModelToDto = (
    model?: Partial<SelfWatcherConfig>,
): SelfWatcherConfigDto => ({
    ...definedFields([
        ['enabled', model?.enabled],
        ['mismatch_threshold', model?.mismatchThreshold],
        ['nightly_reflection_enabled', model?.nightlyReflectionEnabled],
        ['lookback_days', model?.lookbackDays],
        ['max_events_in_cluster', model?.maxEventsInCluster],
        ['llm_max_tokens', model?.llmMaxTokens],
        ['llm_temperature', model?.llmTemperature],
    ]),
    ...promptField('reflection_prompt', model?.reflectionPrompt),
}) as SelfWatcherConfigDto;
