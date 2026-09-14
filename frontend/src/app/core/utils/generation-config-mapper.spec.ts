import { mapGenerationModelToDto } from './generation-config-mapper';

describe('generation config mapper: partial saves', () => {
    it('sends only the fields it carries, with no defaults', () => {
        expect(mapGenerationModelToDto({ temperature: 1.1 })).toEqual({ temperature: 1.1 } as any);
        expect(mapGenerationModelToDto({})).toEqual({} as any);
    });

    it('renames fields and keeps a cleared stop list', () => {
        expect(mapGenerationModelToDto({ topP: 0.8, numPredict: 512, stop: null, normalizeMessages: true })).toEqual({
            top_p: 0.8,
            num_predict: 512,
            stop: null,
            normalize_messages: true,
        } as any);
    });
});
