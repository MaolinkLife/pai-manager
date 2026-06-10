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

const mapSherpaModelToDto = (model?: SttSherpaOnnxConfig): SttSherpaOnnxConfigDto => ({
    model_type: model?.modelType ?? 'transducer',
    encoder: model?.encoder ?? '',
    decoder: model?.decoder ?? '',
    joiner: model?.joiner ?? '',
    paraformer: model?.paraformer ?? '',
    whisper_encoder: model?.whisperEncoder ?? '',
    whisper_decoder: model?.whisperDecoder ?? '',
    moonshine_preprocessor: model?.moonshinePreprocessor ?? '',
    moonshine_encoder: model?.moonshineEncoder ?? '',
    moonshine_uncached_decoder: model?.moonshineUncachedDecoder ?? '',
    moonshine_cached_decoder: model?.moonshineCachedDecoder ?? '',
    tokens: model?.tokens ?? '',
    num_threads: model?.numThreads ?? 1,
    provider: model?.provider ?? 'cpu',
});

export const mapSttDtoToModel = (dto?: SttConfigDto): SttConfig => ({
    language: dto?.language ?? 'en-US',
    autoDetect: dto?.auto_detect ?? false,
    provider: dto?.provider ?? 'whisper',
    sherpaOnnx: mapSherpaDtoToModel(dto?.sherpa_onnx),
});

export const mapSttModelToDto = (model?: SttConfig): SttConfigDto => ({
    language: model?.language ?? 'en-US',
    auto_detect: model?.autoDetect ?? false,
    provider: model?.provider ?? 'whisper',
    sherpa_onnx: mapSherpaModelToDto(model?.sherpaOnnx),
});
