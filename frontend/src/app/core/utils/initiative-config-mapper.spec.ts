import { mapInitiativeDtoToModel, mapInitiativeModelToDto } from './initiative-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';
import { ProjectConfig } from '../models/project-config.model';

const partialSave = (initiative: unknown) =>
    mapPartialModelToDto({ initiative } as Partial<ProjectConfig>).initiative as unknown;

describe('initiative config mapper', () => {
    it('reads a missing section as switched off with the main chat defaults', () => {
        expect(mapInitiativeDtoToModel(undefined)).toEqual({
            enabled: false,
            chat: { enabled: true },
            selfie: { enabled: true, chance: 0.4 },
        });
    });

    it('carries the stored values both ways', () => {
        const stored = { enabled: true, chat: { enabled: false }, selfie: { enabled: false, chance: 0.7 } };

        expect(mapInitiativeModelToDto(mapInitiativeDtoToModel(stored))).toEqual(stored);
    });
});

describe('initiative settings save: only the changed fields go to the server', () => {
    it('sends a single changed field alone', () => {
        expect(partialSave({ enabled: true })).toEqual({ enabled: true });
        expect(partialSave({ selfie: { chance: 0.7 } })).toEqual({ selfie: { chance: 0.7 } });
        expect(partialSave({ chat: { enabled: false } })).toEqual({ chat: { enabled: false } });
    });

    it('sends nothing for an empty save', () => {
        expect(partialSave({})).toEqual({});
    });
});
