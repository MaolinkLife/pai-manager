import { ProjectConfigDto } from '../models/project-config.dto';
import { ProjectConfig } from '../models/project-config.model';

export const mapProjectConfigDtoToModel = (dto: ProjectConfigDto): ProjectConfig => ({
    charName: dto.char_name,
    userName: dto.user_name,
    voice: {
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
    voice: {
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
