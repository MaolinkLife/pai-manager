import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { AudioSettingsComponent } from './audio-settings.component';

describe('AudioSettingsComponent: partial saves', () => {
    let saved: any[];

    const stored = () => ({
        modules: { vtubeStudio: false, whisper: false, minecraft: false, gaming: false, alarm: false, discord: true, rag: true, visual: true },
        audio: {
            inputDeviceId: 2,
            sampleRate: 16000,
            channels: 1,
            chunkSize: 1024,
            enableVad: true,
            vadThreshold: 0.5,
            silenceTimeout: 3,
            minAudioLength: 0.5,
            maxAudioLength: 30,
            triggerWords: ['hey'],
            ignoreTriggerWords: false,
        },
        stt: {
            language: 'ru-RU',
            autoDetect: false,
            provider: 'whisper',
            sherpaOnnx: {
                modelType: 'transducer',
                encoder: 'encoder.onnx',
                decoder: '',
                joiner: '',
                paraformer: '',
                whisperEncoder: '',
                whisperDecoder: '',
                moonshinePreprocessor: '',
                moonshineEncoder: '',
                moonshineUncachedDecoder: '',
                moonshineCachedDecoder: '',
                tokens: '',
                numThreads: 2,
                provider: 'cpu',
            },
        },
    });

    function create(config: any = stored()): AudioSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => of(config),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
        };
        const resources: any = { getAudioDevices$: () => of({ recording_devices: [] }) };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const notifications: any = { open: () => undefined };
        const component = new AudioSettingsComponent(
            new UntypedFormBuilder(), configService, resources, localization, notifications,
        );
        component.ngOnInit();
        return component;
    }

    it('has nothing to save right after loading', () => {
        const component = create();

        expect(component.hasChanges()).toBeFalse();
    });

    it('saves one audio field alone', () => {
        const component = create();

        component.audioForm.get('vadThreshold')!.setValue(0.7);
        component.saveChanges();

        expect(saved).toEqual([{ audio: { vadThreshold: 0.7 } }]);
    });

    it('switching speech recognition sends only that module flag', () => {
        const component = create();

        component.audioForm.get('sttEnabled')!.setValue(true);
        component.saveChanges();

        expect(saved).toEqual([{ modules: { whisper: true } }]);
    });

    it('saves one recognizer field without the rest of the recognizer settings', () => {
        const component = create();

        component.audioForm.get('stt.sherpaOnnx.numThreads')!.setValue(4);
        component.saveChanges();

        expect(saved).toEqual([{ stt: { sherpaOnnx: { numThreads: 4 } } }]);
    });

    it('after a save sends only what changed since then', () => {
        const component = create();

        component.audioForm.get('sttEnabled')!.setValue(true);
        component.saveChanges();
        component.audioForm.get('silenceTimeout')!.setValue(5);
        component.saveChanges();

        expect(saved[1]).toEqual({ audio: { silenceTimeout: 5 } });
    });

    it('does not save when the settings could not be loaded', () => {
        const component = create(null);

        component.audioForm.get('vadThreshold')!.setValue(0.7);
        component.saveChanges();

        expect(component.hasChanges()).toBeFalse();
        expect(saved).toEqual([]);
    });
});
