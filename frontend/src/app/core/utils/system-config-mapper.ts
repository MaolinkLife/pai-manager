import { ProjectConfig, SystemSecurityConfig } from '../models/project-config.model';
import { SystemConfigDto } from '../models/project-config.dto';

// How long a sign-in lasts; the server keeps the values within bounds.
const DEFAULT_SECURITY: SystemSecurityConfig = { accessTokenTtlMinutes: 15, refreshTtlDays: 30 };

const mapSecurityDtoToModel = (dto: any): SystemSecurityConfig => ({
    accessTokenTtlMinutes: dto?.access_token_ttl_minutes ?? DEFAULT_SECURITY.accessTokenTtlMinutes,
    refreshTtlDays: dto?.refresh_ttl_days ?? DEFAULT_SECURITY.refreshTtlDays,
});

export const mapSystemDtoToModel = (dto: any, language?: string) => {
    if (!dto || typeof dto !== 'object') {
        return {
            userId: "",
            charName: "",
            userName: "",
            systemPrompt: "",
            language: language || "en-US",
            theme: "Dark",
            security: mapSecurityDtoToModel(undefined),
        };
    }

    return {
        userId: dto.user_id || "",
        charName: dto.char_name || "",
        userName: dto.user_name || "",
        systemPrompt: dto.system_prompt || "",
        language: dto.language || language || "en-US",
        theme: dto.theme || "Dark",
        runtime: {
            modelMemoryProfile:
                dto?.runtime?.model_memory_profile || "low_memory_strict",
        },
        security: mapSecurityDtoToModel(dto.security),
    };
};

export const mapSystemModelToDto = (system: Partial<ProjectConfig['system']>): Partial<SystemConfigDto> => {
    const dto: Partial<SystemConfigDto> = {};

    if (system.userId !== undefined) {
        dto.user_id = system.userId;
    }
    if (system.charName !== undefined) {
        dto.char_name = system.charName;
    }
    if (system.userName !== undefined) {
        dto.user_name = system.userName;
    }
    if (system.systemPrompt !== undefined) {
        dto.system_prompt = system.systemPrompt;
    }
    if (system.language !== undefined) {
        dto.language = system.language;
    }
    if (system.theme !== undefined) {
        dto.theme = system.theme;
    }
    if (system.runtime?.modelMemoryProfile !== undefined) {
        dto.runtime = {
            model_memory_profile: system.runtime.modelMemoryProfile,
        };
    }
    // A save carries only the lifetime it changed.
    const security: NonNullable<SystemConfigDto['security']> = {};
    if (system.security?.accessTokenTtlMinutes !== undefined) {
        security.access_token_ttl_minutes = system.security.accessTokenTtlMinutes;
    }
    if (system.security?.refreshTtlDays !== undefined) {
        security.refresh_ttl_days = system.security.refreshTtlDays;
    }
    if (Object.keys(security).length) {
        dto.security = security;
    }

    return dto;
};
