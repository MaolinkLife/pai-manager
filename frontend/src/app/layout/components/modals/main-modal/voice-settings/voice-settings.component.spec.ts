import { FormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { VoiceSettingsComponent } from './voice-settings.component';

describe('VoiceSettingsComponent: partial saves', () => {
    let saved: any[];
    let component: VoiceSettingsComponent | null = null;

    const stored = () => ({
        voice: {
            enabled: false,
            activeModule: 'edge',
            streamingTts: false,
            enableFallback: true,
            useRvc: false,
            useWindowsOutput: true,
            outputId: 3,
            windowsOutputId: 4,
            voiceModules: {
                edge: { voiceLanguage: 'en-US-AriaNeural' },
                gtts: { language: 'en', tld: 'com', slow: false, fallbackVoice: '' },
                offline: { voice: '' },
                elevenlabs: { apiKey: '', voiceId: '', modelId: '', stability: 0.5, similarity: 0.75 },
            },
        },
    });

    function create(config: any = stored()): VoiceSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => of(config),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({ status: 'ok' });
            },
        };
        const resources: any = {
            getAudioDevices$: () => of({ all_devices: [], get_windows_output: [] }),
            getEdgeVoices$: () => of({ status: 'success', voices: [] }),
            getLocalVoiceFiles$: () => of({ files: [] }),
            getLocalXttsModels$: () => of({ models: [] }),
            getLocalRvcModels$: () => of({ models: [] }),
        };
        const voiceService: any = { providersStatus$: () => of({ status: 'ok', providers: {} }) };
        const notifications: any = { open: () => undefined };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        component = new VoiceSettingsComponent(
            new FormBuilder(), configService, resources, voiceService, notifications, localization, cdr,
        );
        component.ngOnInit();
        return component;
    }

    afterEach(() => {
        component?.ngOnDestroy();
        component = null;
    });

    it('has nothing to save right after loading', () => {
        const voice = create();

        expect(voice.hasChanges()).toBeFalse();
    });

    it('saves a switch without the provider settings', () => {
        const voice = create();

        voice.voiceForm.get('enabled')!.setValue(true);
        voice.saveChanges();

        expect(saved).toEqual([{ voice: { enabled: true } }]);
    });

    it('saves one provider field without the other providers', () => {
        const voice = create();

        voice.voiceForm.get('voiceModules.gtts.slow')!.setValue(true);
        voice.saveChanges();

        expect(saved).toEqual([{ voice: { voiceModules: { gtts: { slow: true } } } }]);
    });

    it('the silent apply sends only what changed as well', () => {
        const voice = create();

        voice.voiceForm.get('voiceModules.edge.voiceLanguage')!.setValue('en-GB-SoniaNeural');
        (voice as any).applyVoiceChangesSilently();

        expect(saved).toEqual([{ voice: { voiceModules: { edge: { voiceLanguage: 'en-GB-SoniaNeural' } } } }]);
    });

    it('does not save when the settings could not be loaded', () => {
        const voice = create({});

        voice.voiceForm.get('enabled')!.setValue(true);
        voice.saveChanges();

        expect(voice.hasChanges()).toBeFalse();
        expect(saved).toEqual([]);
    });
});
