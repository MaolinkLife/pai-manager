import { mapModulesModelToDto } from './modules-config-mapper';
import { mapPartialModelToDto } from './project-config.mapper';
import { mapSttModelToDto } from './stt-config-mapper';

describe('stt and modules config mappers: partial saves', () => {
    it('stt sends only the fields it carries, with no defaults', () => {
        expect(mapSttModelToDto({ language: 'ru-RU' })).toEqual({ language: 'ru-RU' } as any);
        expect(mapSttModelToDto({ sherpaOnnx: { numThreads: 4 } } as any)).toEqual({ sherpa_onnx: { num_threads: 4 } } as any);
        expect(mapSttModelToDto({})).toEqual({} as any);
    });

    it('modules send only the flags they carry', () => {
        expect(mapModulesModelToDto({ whisper: true } as any)).toEqual({ whisper: true } as any);
        expect(mapModulesModelToDto({ vtubeStudio: false } as any)).toEqual({ vtube_studio: false } as any);
    });

    it('a one-field save reaches the server as that field alone', () => {
        expect(mapPartialModelToDto({ modules: { whisper: true }, stt: { autoDetect: true } } as any)).toEqual({
            modules: { whisper: true },
            stt: { auto_detect: true },
        } as any);
    });
});
