import { mapAuditLogsDtoToModel, mapAuditLogsModelToDto } from './audit-logs-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';

describe('audit logs config mapper: defaults', () => {
    it('fills missing retention values with the same defaults as the server', () => {
        const retention = mapAuditLogsDtoToModel({}).retention;

        expect(retention.ageDays).toEqual(expect.objectContaining({ info: 7, success: 7, warning: 30, error: 90, audit_fail: 90 }));
        expect(retention.hardCap).toEqual({ info: 50000, success: 50000, warning: 10000, error: 5000, audit_fail: 5000 });
    });
});

describe('audit logs config mapper: partial saves', () => {
    it('sends only the retention fields it carries, with no defaults', () => {
        expect(mapAuditLogsModelToDto({ retention: { ageDays: { info: 10 } } } as any)).toEqual({
            retention: { age_days: { info: 10 } },
        } as any);
        expect(mapAuditLogsModelToDto({ retention: { enabled: false } } as any)).toEqual({ retention: { enabled: false } } as any);
        expect(mapAuditLogsModelToDto({})).toEqual({} as any);
    });

    it('a one-value save reaches the server as that value alone', () => {
        expect(mapPartialModelToDto({ auditLogs: { retention: { hardCap: { error: 1000 } } } } as any)).toEqual({
            audit_logs: { retention: { hard_cap: { error: 1000 } } },
        } as any);
    });
});
