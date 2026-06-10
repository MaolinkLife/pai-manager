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
    success: 14,
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

const mapRetentionModelToDto = (
    model?: AuditLogsRetentionConfig,
): AuditLogsRetentionConfigDto => ({
    enabled: model?.enabled ?? true,
    age_days: model?.ageDays ?? DEFAULT_AGE_DAYS,
    hard_cap: model?.hardCap ?? DEFAULT_HARD_CAP,
});

export const mapAuditLogsDtoToModel = (dto?: AuditLogsConfigDto): AuditLogsConfig => ({
    retention: mapRetentionDtoToModel(dto?.retention),
});

export const mapAuditLogsModelToDto = (model?: AuditLogsConfig): AuditLogsConfigDto => ({
    retention: mapRetentionModelToDto(model?.retention),
});
