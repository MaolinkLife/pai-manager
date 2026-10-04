import { ProjectConfigDto } from '../models/project-config.dto';
import { mapVisionDtoToModel, mapVisionModelToDto } from './vision-config-mapper';

describe('vision config mapper', () => {
    it('keeps background screen capture off when the server sends no switch', () => {
        const model = mapVisionDtoToModel({ enabled: true } as ProjectConfigDto['vision']);

        expect(model.enabled).toBe(true);
        expect(model.screenCaptureEnabled).toBe(false);
    });

    it('carries the background screen capture switch both ways', () => {
        const model = mapVisionDtoToModel({ enabled: true, screen_capture_enabled: true } as ProjectConfigDto['vision']);

        expect(model.screenCaptureEnabled).toBe(true);
        expect(mapVisionModelToDto({ screenCaptureEnabled: false })).toEqual({ screen_capture_enabled: false } as ProjectConfigDto['vision']);
    });

    it('carries the vision prompts both ways and sends only the one that changed', () => {
        const model = mapVisionDtoToModel({
            enabled: true,
            attachment_prompt: 'what they sent',
            generated_image_prompt: 'what I drew',
            screen_prompt: 'what is on the screen',
        } as ProjectConfigDto['vision']);

        expect([model.attachmentPrompt, model.generatedImagePrompt, model.screenPrompt]).toEqual([
            'what they sent',
            'what I drew',
            'what is on the screen',
        ]);
        expect(mapVisionModelToDto({ screenPrompt: '' })).toEqual({ screen_prompt: '' } as ProjectConfigDto['vision']);
    });
});
