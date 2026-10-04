import {
    mapConfidenceDtoToModel,
    mapFactualityModelToDto,
    mapLanguageGuardModelToDto,
    mapSelfWatcherDtoToModel,
    mapSelfWatcherModelToDto,
    mapValidatorDtoToModel,
    mapValidatorModelToDto,
} from './compliance-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';
import { SelfWatcherConfig, ValidatorConfig } from '../models/project-config.model';

describe('compliance config mapper: partial saves', () => {
    it('sends only the fields it carries, with no defaults', () => {
        expect(mapFactualityModelToDto({ topK: 5 })).toEqual({ top_k: 5 });
        expect(mapLanguageGuardModelToDto({})).toEqual({});
        expect(mapValidatorModelToDto({ enabled: false })).toEqual({ enabled: false });
    });

    it('a one-field save reaches the server as that field alone', () => {
        const dto = mapPartialModelToDto({ confidence: { threshold: 0.4 } } as any);

        expect(dto).toEqual({ confidence: { threshold: 0.4 } });
    });
});

describe('compliance config mapper: technical prompts', () => {
    it('carries the prompts from the server into the form', () => {
        expect(mapValidatorDtoToModel({ system_prompt: 'judge' }).systemPrompt).toBe('judge');
        expect(mapConfidenceDtoToModel({ system_prompt: 'estimate' }).systemPrompt).toBe('estimate');
        expect(mapSelfWatcherDtoToModel({ reflection_prompt: 'reflect in {language}' }).reflectionPrompt).toBe('reflect in {language}');
    });

    it('sends an edited prompt, and an emptied one as empty', () => {
        const validator = { ...mapValidatorDtoToModel({}), systemPrompt: 'judge strictly' };
        const selfWatcher = { ...mapSelfWatcherDtoToModel({}), reflectionPrompt: '' };

        expect(mapValidatorModelToDto(validator).system_prompt).toBe('judge strictly');
        expect(mapSelfWatcherModelToDto(selfWatcher).reflection_prompt).toBe('');
    });

    it('does not wipe a prompt the form never loaded', () => {
        const { systemPrompt, ...validator } = mapValidatorDtoToModel({});
        const { reflectionPrompt, ...selfWatcher } = mapSelfWatcherDtoToModel({});

        expect('system_prompt' in mapValidatorModelToDto(validator as ValidatorConfig)).toBe(false);
        expect('reflection_prompt' in mapSelfWatcherModelToDto(selfWatcher as SelfWatcherConfig)).toBe(false);
    });
});
