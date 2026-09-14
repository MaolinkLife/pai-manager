import { ConnectorConfigDto, TunnelingConfigDto } from '../models/project-config.dto';
import { ConnectorConfig, TunnelingConfig } from '../models/project-config.model';

const DEFAULT_TUNNELING: TunnelingConfig = {
    enabled: false,
    provider: 'cloudflared',
    localUrl: 'http://127.0.0.1:3880',
    localPort: 3880,
    commandPath: '',
    publicUrl: '',
};

export const mapTunnelingDtoToModel = (
    dto: Partial<TunnelingConfigDto> | undefined
): TunnelingConfig => ({
    enabled: dto?.enabled ?? DEFAULT_TUNNELING.enabled,
    provider: dto?.provider ?? DEFAULT_TUNNELING.provider,
    localUrl: dto?.local_url ?? DEFAULT_TUNNELING.localUrl,
    localPort: dto?.local_port ?? DEFAULT_TUNNELING.localPort,
    commandPath: dto?.command_path ?? DEFAULT_TUNNELING.commandPath,
    publicUrl: dto?.public_url ?? DEFAULT_TUNNELING.publicUrl,
});

export const mapConnectorDtoToModel = (
    dto: Partial<ConnectorConfigDto> | undefined
): ConnectorConfig => ({
    tunneling: mapTunnelingDtoToModel(dto?.tunneling),
});

const TUNNELING_FIELD_NAMES: Array<[keyof TunnelingConfig, string]> = [
    ['enabled', 'enabled'],
    ['provider', 'provider'],
    ['localUrl', 'local_url'],
    ['localPort', 'local_port'],
    ['commandPath', 'command_path'],
    ['publicUrl', 'public_url'],
];

/** A settings save sends only the fields it carries — nothing is filled with defaults. */
export const mapTunnelingModelToDto = (
    model: Partial<TunnelingConfig> | undefined
): TunnelingConfigDto => {
    const dto: Record<string, unknown> = {};
    TUNNELING_FIELD_NAMES.forEach(([from, to]) => {
        const value = model?.[from];
        if (value !== undefined) {
            dto[to] = value;
        }
    });
    return dto as unknown as TunnelingConfigDto;
};

export const mapConnectorModelToDto = (
    model: Partial<ConnectorConfig> | undefined
): ConnectorConfigDto => {
    const dto: Record<string, unknown> = {};
    if (model?.tunneling !== undefined) {
        dto['tunneling'] = mapTunnelingModelToDto(model.tunneling);
    }
    return dto as unknown as ConnectorConfigDto;
};
