import { InitiativeConfigDto } from '../models/project-config.dto';
import { InitiativeConfig, InitiativeConfigPatch } from '../models/project-config.model';

// Mirrors constants/default_config.py: the global switch is off on a fresh install.
export const mapInitiativeDtoToModel = (dto?: InitiativeConfigDto): InitiativeConfig => ({
    enabled: dto?.enabled ?? false,
    chat: { enabled: dto?.chat?.enabled ?? true },
    selfie: {
        enabled: dto?.selfie?.enabled ?? true,
        chance: dto?.selfie?.chance ?? 0.4,
    },
});

export const mapInitiativeModelToDto = (model?: InitiativeConfig): InitiativeConfigDto => ({
    enabled: model?.enabled ?? false,
    chat: { enabled: model?.chat?.enabled ?? true },
    selfie: {
        enabled: model?.selfie?.enabled ?? true,
        chance: Number(model?.selfie?.chance ?? 0.4),
    },
});

/** A settings save sends only the fields it carries — nothing is filled with defaults. */
export const mapInitiativePartialModelToDto = (model?: InitiativeConfigPatch): InitiativeConfigDto => {
    const dto: InitiativeConfigDto = {};
    if (!model) {
        return dto;
    }
    if (model.enabled !== undefined) {
        dto.enabled = model.enabled;
    }
    if (model.chat?.enabled !== undefined) {
        dto.chat = { enabled: model.chat.enabled };
    }
    if (model.selfie) {
        const selfie: InitiativeConfigDto['selfie'] = {};
        if (model.selfie.enabled !== undefined) {
            selfie.enabled = model.selfie.enabled;
        }
        if (model.selfie.chance !== undefined) {
            selfie.chance = Number(model.selfie.chance);
        }
        if (Object.keys(selfie).length > 0) {
            dto.selfie = selfie;
        }
    }
    return dto;
};
