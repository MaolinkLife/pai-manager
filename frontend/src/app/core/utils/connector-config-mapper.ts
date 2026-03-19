import { ConnectorConfigDto, TunnelingConfigDto } from '../models/project-config.dto';
import { ConnectorConfig, TunnelingConfig } from '../models/project-config.model';

const DEFAULT_TUNNELING: TunnelingConfig = {
    enabled: false,
    provider: 'cloudflared',
    localUrl: 'http://127.0.0.1:4200',
    localPort: 4200,
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

export const mapTunnelingModelToDto = (
    model: Partial<TunnelingConfig> | undefined
): TunnelingConfigDto => ({
    enabled: model?.enabled ?? DEFAULT_TUNNELING.enabled,
    provider: model?.provider ?? DEFAULT_TUNNELING.provider,
    local_url: model?.localUrl ?? DEFAULT_TUNNELING.localUrl,
    local_port: model?.localPort ?? DEFAULT_TUNNELING.localPort,
    command_path: model?.commandPath ?? DEFAULT_TUNNELING.commandPath,
    public_url: model?.publicUrl ?? DEFAULT_TUNNELING.publicUrl,
});

export const mapConnectorModelToDto = (
    model: Partial<ConnectorConfig> | undefined
): ConnectorConfigDto => ({
    tunneling: mapTunnelingModelToDto(model?.tunneling),
});
