import {
    AuditLogsConfigDto,
    AuditLogsRetentionConfigDto,
} from '../models/project-config.dto';
import {
    AuditLogsConfig,
    AuditLogsRetentionConfig,
} from '../models/project-config.model';

// Default retention buckets mirror backend modules/system/logger.prune_audit_logs.
const DEFAULT_AGE_DAYS: Record<string, number> = {
    debug: 7,
    info: 7,
    success: 7,
    warning: 30,
    error: 90,
    audit_fail: 90,
};

const DEFAULT_HARD_CAP: Record<string, number> = {
    info: 50000,
    success: 50000,
    warning: 10000,
    error: 5000,
    audit_fail: 5000,
};

const mapRetentionDtoToModel = (
    dto?: AuditLogsRetentionConfigDto,
): AuditLogsRetentionConfig => ({
    enabled: dto?.enabled ?? true,
    ageDays: { ...DEFAULT_AGE_DAYS, ...(dto?.age_days ?? {}) },
    hardCap: { ...DEFAULT_HARD_CAP, ...(dto?.hard_cap ?? {}) },
});

/** A settings save sends only the fields it carries — nothing is filled with defaults. */
const mapRetentionModelToDto = (
    model?: Partial<AuditLogsRetentionConfig>,
): AuditLogsRetentionConfigDto => {
    const dto: Record<string, unknown> = {};
    if (model?.enabled !== undefined) {
        dto['enabled'] = model.enabled;
    }
    if (model?.ageDays !== undefined) {
        dto['age_days'] = model.ageDays;
    }
    if (model?.hardCap !== undefined) {
        dto['hard_cap'] = model.hardCap;
    }
    return dto as unknown as AuditLogsRetentionConfigDto;
};

export const mapAuditLogsDtoToModel = (dto?: AuditLogsConfigDto): AuditLogsConfig => ({
    retention: mapRetentionDtoToModel(dto?.retention),
});

export const mapAuditLogsModelToDto = (model?: Partial<AuditLogsConfig>): AuditLogsConfigDto => {
    const dto: Record<string, unknown> = {};
    if (model?.retention !== undefined) {
        dto['retention'] = mapRetentionModelToDto(model.retention);
    }
    return dto as unknown as AuditLogsConfigDto;
};
