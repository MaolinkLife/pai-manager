import { mapAuditLogsModelToDto } from './audit-logs-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';

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
