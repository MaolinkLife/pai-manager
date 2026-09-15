import { mapSystemDtoToModel, mapSystemModelToDto } from './system-config-mapper';

describe('system config mapper: sign-in lifetimes', () => {
    it('reads the stored lifetimes', () => {
        const model = mapSystemDtoToModel({ security: { access_token_ttl_minutes: 20, refresh_ttl_days: 60 } });

        expect(model.security).toEqual({ accessTokenTtlMinutes: 20, refreshTtlDays: 60 });
    });

    it('falls back to fifteen minutes and thirty days', () => {
        expect(mapSystemDtoToModel({}).security).toEqual({ accessTokenTtlMinutes: 15, refreshTtlDays: 30 });
        expect(mapSystemDtoToModel(null).security).toEqual({ accessTokenTtlMinutes: 15, refreshTtlDays: 30 });
    });

    it('writes only the lifetime that is part of the save', () => {
        expect(mapSystemModelToDto({ security: { refreshTtlDays: 60 } } as any)).toEqual({ security: { refresh_ttl_days: 60 } });
        expect(mapSystemModelToDto({ userName: 'You' })).toEqual({ user_name: 'You' });
    });
});
