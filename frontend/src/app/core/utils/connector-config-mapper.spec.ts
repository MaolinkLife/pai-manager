import { mapConnectorModelToDto } from './connector-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';

describe('connector config mapper: partial saves', () => {
    it('sends only the tunnel fields it carries, with no defaults', () => {
        expect(mapConnectorModelToDto({ tunneling: { enabled: true } } as any)).toEqual({ tunneling: { enabled: true } } as any);
        expect(mapConnectorModelToDto({ tunneling: { commandPath: 'C:/tools/cloudflared.exe' } } as any)).toEqual({
            tunneling: { command_path: 'C:/tools/cloudflared.exe' },
        } as any);
        expect(mapConnectorModelToDto({})).toEqual({} as any);
    });

    it('a one-field save reaches the server as that field alone', () => {
        expect(mapPartialModelToDto({ connector: { tunneling: { provider: 'localtunnel' } } } as any)).toEqual({
            connector: { tunneling: { provider: 'localtunnel' } },
        } as any);
    });
});
