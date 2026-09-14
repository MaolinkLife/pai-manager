import {
    SttConfigDto,
    SttSherpaOnnxConfigDto,
} from '../models/project-config.dto';
import { SttConfig, SttSherpaOnnxConfig } from '../models/project-config.model';

const mapSherpaDtoToModel = (dto?: SttSherpaOnnxConfigDto): SttSherpaOnnxConfig => ({
    modelType: dto?.model_type ?? 'transducer',
    encoder: dto?.encoder ?? '',
    decoder: dto?.decoder ?? '',
    joiner: dto?.joiner ?? '',
    paraformer: dto?.paraformer ?? '',
    whisperEncoder: dto?.whisper_encoder ?? '',
    whisperDecoder: dto?.whisper_decoder ?? '',
    moonshinePreprocessor: dto?.moonshine_preprocessor ?? '',
    moonshineEncoder: dto?.moonshine_encoder ?? '',
    moonshineUncachedDecoder: dto?.moonshine_uncached_decoder ?? '',
    moonshineCachedDecoder: dto?.moonshine_cached_decoder ?? '',
    tokens: dto?.tokens ?? '',
    numThreads: dto?.num_threads ?? 1,
    provider: dto?.provider ?? 'cpu',
});

const SHERPA_FIELD_NAMES: Array<[keyof SttSherpaOnnxConfig, string]> = [
    ['modelType', 'model_type'],
    ['encoder', 'encoder'],
    ['decoder', 'decoder'],
    ['joiner', 'joiner'],
    ['paraformer', 'paraformer'],
    ['whisperEncoder', 'whisper_encoder'],
    ['whisperDecoder', 'whisper_decoder'],
    ['moonshinePreprocessor', 'moonshine_preprocessor'],
    ['moonshineEncoder', 'moonshine_encoder'],
    ['moonshineUncachedDecoder', 'moonshine_uncached_decoder'],
    ['moonshineCachedDecoder', 'moonshine_cached_decoder'],
    ['tokens', 'tokens'],
    ['numThreads', 'num_threads'],
    ['provider', 'provider'],
];

const mapSherpaModelToDto = (model?: Partial<SttSherpaOnnxConfig>): SttSherpaOnnxConfigDto => {
    const dto: Record<string, unknown> = {};
    SHERPA_FIELD_NAMES.forEach(([from, to]) => {
        const value = model?.[from];
        if (value !== undefined) {
            dto[to] = value;
        }
    });
    return dto as SttSherpaOnnxConfigDto;
};

export const mapSttDtoToModel = (dto?: SttConfigDto): SttConfig => ({
    language: dto?.language ?? 'en-US',
    autoDetect: dto?.auto_detect ?? false,
    provider: dto?.provider ?? 'whisper',
    sherpaOnnx: mapSherpaDtoToModel(dto?.sherpa_onnx),
});

/** A settings save sends only the fields it carries — nothing is filled with defaults. */
export const mapSttModelToDto = (model?: Partial<SttConfig>): SttConfigDto => {
    const dto: Record<string, unknown> = {};
    if (model?.language !== undefined) {
        dto['language'] = model.language;
    }
    if (model?.autoDetect !== undefined) {
        dto['auto_detect'] = model.autoDetect;
    }
    if (model?.provider !== undefined) {
        dto['provider'] = model.provider;
    }
    if (model?.sherpaOnnx !== undefined) {
        dto['sherpa_onnx'] = mapSherpaModelToDto(model.sherpaOnnx);
    }
    return dto as SttConfigDto;
};
