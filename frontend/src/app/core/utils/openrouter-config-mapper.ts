import { ProjectConfig } from '../models/project-config.model';

export const mapOpenRouterDtoToModel = (dto: any) => ({
    apiKey: dto.api_key,
    model: dto.model,
});

export const mapOpenRouterModelToDto = (openrouter: ProjectConfig['openrouter']) => ({
    api_key: openrouter.apiKey,
    model: openrouter.model,
});
