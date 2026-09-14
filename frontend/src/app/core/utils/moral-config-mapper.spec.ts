import { mapMoralDtoToModel, mapMoralPartialModelToDto } from './moral-config-mapper';
import { MoralConfig, MoralInnerVoiceConfig } from '../models/project-config.model';
import { MoralConfigDto } from '../models/project-config.dto';

describe('moral config mapper: inner voice prompt', () => {
    it('carries the prompt from the server into the form and back', () => {
        const model = mapMoralDtoToModel({
            enabled: true,
            active_provider: 'ollama',
            fallback_order: ['heuristic'],
            providers: {},
            inner_voice: { enabled: true, max_tokens: 80, temperature: 0.7, language: '', system_prompt: 'why I feel it' },
        } as MoralConfigDto);

        expect(model.innerVoice?.systemPrompt).toBe('why I feel it');
        expect(mapMoralPartialModelToDto({ innerVoice: model.innerVoice } as Partial<MoralConfig>)?.inner_voice?.system_prompt).toBe('why I feel it');
    });

    it('does not wipe the prompt when a save changes something else', () => {
        const changed = { innerVoice: { temperature: 0.9 } as MoralInnerVoiceConfig } as Partial<MoralConfig>;

        const dto = mapMoralPartialModelToDto(changed);

        expect('system_prompt' in (dto?.inner_voice ?? {})).toBeFalse();
    });
});

describe('moral config mapper: partial saves', () => {
    it('switching scars does not send an empty trigger list', () => {
        const dto = mapMoralPartialModelToDto({ scars: { enabled: true } } as Partial<MoralConfig>);

        expect(dto?.scars).toEqual({ enabled: true } as any);
    });

    it('edited triggers are sent as the whole list', () => {
        const trigger = { name: 'insult', intents: ['insult'], tones: [], keywords: [], persistenceFloor: 0.4, intensityBoost: 0.2 };

        const dto = mapMoralPartialModelToDto({ scars: { triggers: [trigger] } } as unknown as Partial<MoralConfig>);

        expect(dto?.scars?.triggers).toEqual([{
            name: 'insult', intents: ['insult'], tones: [], keywords: [], persistence_floor: 0.4, intensity_boost: 0.2,
        }]);
    });
});
