import { ProjectConfigDto } from '../models/project-config.dto';
import { ProjectConfig } from '../models/project-config.model';

export const mapProjectConfigDtoToModel = (dto: ProjectConfigDto): ProjectConfig => ({
    charName: dto.char_name,
    userName: dto.user_name,
    language: dto.language,
    voice: {
        enabled: dto.voice.enabled,
        outputId: dto.voice.output_id,
        windowsOutputId: dto.voice.windows_output_id,
        language: dto.voice.language,
        useRvc: dto.voice.use_rvc,
        voiceLanguage: dto.voice.voice_language,
    },
    modules: dto.modules,
    api: {
        type: dto.api.type,
        streaming: dto.api.streaming,
        model: dto.api.model,
        visualModel: dto.api.visual_model,
        tokenLimit: dto.api.token_limit,
        messagePairLimit: dto.api.message_pair_limit,
    },
});

export const mapProjectConfigModelToDto = (model: ProjectConfig): ProjectConfigDto => ({
    char_name: model.charName,
    user_name: model.userName,
    language: model.language,
    voice: {
        enabled: model.voice.enabled,
        output_id: model.voice.outputId,
        windows_output_id: model.voice.windowsOutputId,
        language: model.voice.language,
        use_rvc: model.voice.useRvc,
        voice_language: model.voice.voiceLanguage,
    },
    modules: {
        vtube_studio: model.modules.vtube_studio,
        whisper: model.modules.whisper,
        minecraft: model.modules.minecraft,
        gaming: model.modules.gaming,
        alarm: model.modules.alarm,
        discord: model.modules.discord,
        rag: model.modules.rag,
        visual: model.modules.visual,
    },
    api: {
        type: model.api.type,
        streaming: model.api.streaming,
        model: model.api.model,
        visual_model: model.api.visualModel,
        token_limit: model.api.tokenLimit,
        message_pair_limit: model.api.messagePairLimit,
    },
});

export const mapPartialModelToDto = (
    model: Partial<ProjectConfig>
): Partial<ProjectConfigDto> => {
    const dto: Partial<ProjectConfigDto> = {};

    const allowedKeys = ['charName', 'userName', 'language', 'voice', 'modules', 'api'];

    Object.keys(model).forEach((key) => {
        if (!allowedKeys.includes(key)) {
            throw new Error(`Unexpected field "${key}" in ProjectConfig`);
        }

        switch (key) {
            case 'charName':
                dto.char_name = model.charName!;
                break;
            case 'userName':
                dto.user_name = model.userName!;
                break;
            case 'language':
                dto.language = model.language!;
                break;
            case 'voice':
                dto.voice = mapVoiceModelToDto(model.voice!);
                break;
            case 'modules':
                dto.modules = mapModulesModelToDto(model.modules!);
                break;
            case 'api':
                dto.api = mapApiModelToDto(model.api!);
                break;
        }
    });

    return dto;
};


const mapVoiceModelToDto = (voice: ProjectConfig['voice']) => ({
    output_id: voice.outputId,
    windows_output_id: voice.windowsOutputId,
    language: voice.language,
    use_rvc: voice.useRvc,
    voice_language: voice.voiceLanguage,
    enabled: voice.enabled,
});

const mapModulesModelToDto = (modules: ProjectConfig['modules']) => ({
    vtube_studio: modules.vtube_studio,
    whisper: modules.whisper,
    minecraft: modules.minecraft,
    gaming: modules.gaming,
    alarm: modules.alarm,
    discord: modules.discord,
    rag: modules.rag,
    visual: modules.visual,
});

const mapApiModelToDto = (api: ProjectConfig['api']) => ({
    type: api.type,
    streaming: api.streaming,
    model: api.model,
    visual_model: api.visualModel,
    token_limit: api.tokenLimit,
    message_pair_limit: api.messagePairLimit,
});
