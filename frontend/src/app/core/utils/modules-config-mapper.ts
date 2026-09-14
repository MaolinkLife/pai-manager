import { ProjectConfigDto } from '../models/project-config.dto';
import { ProjectConfig } from '../models/project-config.model';

export const mapModulesDtoToModel = (dto: any) => ({
    vtubeStudio: dto.vtube_studio,
    whisper: dto.whisper,
    minecraft: dto.minecraft,
    gaming: dto.gaming,
    alarm: dto.alarm,
    discord: dto.discord,
    rag: dto.rag,
    visual: dto.visual,
});

const MODULE_FIELD_NAMES: Array<[string, string]> = [
    ['vtubeStudio', 'vtube_studio'],
    ['whisper', 'whisper'],
    ['minecraft', 'minecraft'],
    ['gaming', 'gaming'],
    ['alarm', 'alarm'],
    ['discord', 'discord'],
    ['rag', 'rag'],
    ['visual', 'visual'],
];

/** A settings save sends only the module flags it carries. */
export const mapModulesModelToDto = (modules: Partial<ProjectConfig['modules']>): ProjectConfigDto['modules'] => {
    const dto: Record<string, unknown> = {};
    MODULE_FIELD_NAMES.forEach(([from, to]) => {
        const value = (modules as Record<string, unknown> | undefined)?.[from];
        if (value !== undefined) {
            dto[to] = value;
        }
    });
    return dto as unknown as ProjectConfigDto['modules'];
};
