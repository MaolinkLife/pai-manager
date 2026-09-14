import { mapPartialModelToDto } from './project-config.mapper';
import { mapVoiceModelToDto } from './voice-config-mapper';

describe('voice config mapper: partial saves', () => {
    it('sends only the fields it carries', () => {
        expect(mapVoiceModelToDto({ enabled: true } as any)).toEqual({ enabled: true });
        expect(mapVoiceModelToDto({ activeModule: 'edge' } as any)).toEqual({ active_module: 'edge' });
        expect(mapVoiceModelToDto({} as any)).toEqual({});
    });

    it('renames one provider field for the server without its neighbours', () => {
        expect(mapVoiceModelToDto({ voiceModules: { elevenlabs: { voiceId: 'abc' } } } as any)).toEqual({
            voice_modules: { elevenlabs: { voice_id: 'abc' } },
        });
    });

    it('a one-field save reaches the server as that field alone', () => {
        expect(mapPartialModelToDto({ voice: { voiceModules: { gtts: { slow: true } } } } as any)).toEqual({
            voice: { voice_modules: { gtts: { slow: true } } },
        } as any);
    });
});
