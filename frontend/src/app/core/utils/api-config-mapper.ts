import { ProjectConfig } from '../models/project-config.model';

export const mapApiDtoToModel = (dto: any) => ({
    type: dto.type,
    streaming: dto.streaming,
    model: dto.model,
    visualModel: dto.visual_model,
    tokenLimit: dto.token_limit,
    messagePairLimit: dto.message_pair_limit,
});

export const mapApiModelToDto = (api: ProjectConfig['api']) => ({
    type: api.type,
    streaming: api.streaming,
    model: api.model,
    visual_model: api.visualModel,
    token_limit: api.tokenLimit,
    message_pair_limit: api.messagePairLimit,
});
