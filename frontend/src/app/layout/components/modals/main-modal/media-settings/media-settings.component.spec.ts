import { UntypedFormBuilder } from '@angular/forms';
import { Observable, of, throwError } from 'rxjs';
import { IMAGE_CHECK_DEFAULTS } from './image-check-settings';
import { MediaSettingsComponent } from './media-settings.component';

const BUILT_IN: Record<string, string> = {
    'synthesis.image_check.system_prompt': 'Built-in judge.',
    'synthesis.prompting.image_prompt_builder_user_template': 'Built-in {tool_context}',
};

describe('MediaSettingsComponent image check', () => {
    let saved: any[];

    function create(synthesis: any, config$?: Observable<any>): MediaSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => config$ ?? of({ synthesis }),
            getDefaultValue$: (path: string) => of(BUILT_IN[path] ?? null),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
        };
        const synthesisService: any = {
            getModels$: () => of({ models: [] }),
            getComfyUIStatus$: () => of({}),
            invalidateCache: () => undefined,
        };
        const notifications: any = { success: () => undefined, error: () => undefined };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        const component = new MediaSettingsComponent(
            new UntypedFormBuilder(), configService, synthesisService, notifications, localization, cdr,
        );
        component.ngOnInit();
        return component;
    }

    const control = (component: MediaSettingsComponent, path: string) => component.mediaForm.get(`image_check.${path}`)!;

    it('shows the stored settings and locks what a switched-off check cannot use', () => {
        const component = create({
            image_check: {
                relevance: { enabled: true, threshold: 0.6, reroll: false },
                quality: { enabled: false, threshold: 0.9, reroll: false },
                max_generations: 2,
                system_prompt: 'Judge.',
            },
        });

        expect(control(component, 'quality.threshold').value).toBe(0.9);
        expect(control(component, 'system_prompt').value).toBe('Judge.');
        expect(control(component, 'quality.threshold').disabled).toBeTrue();
        expect(control(component, 'quality.reroll').disabled).toBeTrue();
        expect(control(component, 'relevance.threshold').enabled).toBeTrue();
        expect(control(component, 'relevance.reroll').enabled).toBeTrue();
        expect(control(component, 'max_generations').disabled).toBeTrue();
    });

    it('unlocks the generation count only while an enabled check may request a new image', () => {
        const component = create({});

        control(component, 'relevance.reroll').setValue(true);
        expect(control(component, 'max_generations').enabled).toBeTrue();

        control(component, 'relevance.enabled').setValue(false);
        expect(control(component, 'relevance.reroll').disabled).toBeTrue();
        expect(control(component, 'max_generations').disabled).toBeTrue();
    });

    it('warns above three generations only while a new image can be requested', () => {
        const component = create({});
        control(component, 'relevance.reroll').setValue(true);

        control(component, 'max_generations').setValue(3);
        expect(component.showGenerationsWarning).toBeFalse();
        control(component, 'max_generations').setValue(4);
        expect(component.showGenerationsWarning).toBeTrue();

        control(component, 'relevance.reroll').setValue(false);
        expect(component.showGenerationsWarning).toBeFalse();
    });

    it('falls back to the defaults when the config has no check', () => {
        const component = create({});

        expect(component.mediaForm.getRawValue().image_check).toEqual(IMAGE_CHECK_DEFAULTS);
    });

    it('saves only the changed check values, in range, without keys the form does not know', () => {
        const component = create({
            image_check: { ...IMAGE_CHECK_DEFAULTS, system_prompt: 'Judge.', future_flag: true },
        });

        control(component, 'relevance.reroll').setValue(true);
        control(component, 'relevance.threshold').setValue(0.567);
        control(component, 'max_generations').setValue(99);
        component.saveChanges();

        expect(saved).toEqual([{
            synthesis: {
                image_check: {
                    relevance: { threshold: 0.57, reroll: true },
                    max_generations: 10,
                },
            },
        }]);
    });

    it('loads the scene answer format and saves only its change', () => {
        const component = create({ image_scene: { format_prompt: 'Return JSON.', future_flag: true } });

        expect(component.mediaForm.get('image_scene.format_prompt')!.value).toBe('Return JSON.');
        component.mediaForm.get('image_scene.format_prompt')!.setValue('Return strict JSON.');
        component.saveChanges();

        expect(saved).toEqual([{ synthesis: { image_scene: { format_prompt: 'Return strict JSON.' } } }]);
    });

    it('has no old assessment fields and leaves the hidden prompt-engineering switch alone', () => {
        const component = create({ prompting: { enabled: false, default_negative_prompt: 'x' } });

        ['assess_enabled', 'quality_threshold', 'max_attempts', 'retry_enabled', 'enabled'].forEach((key) => {
            expect(component.mediaForm.get(`prompting.${key}`)).withContext(key).toBeNull();
        });

        control(component, 'relevance.threshold').setValue(0.7);
        component.saveChanges();

        expect(saved).toEqual([{ synthesis: { image_check: { relevance: { threshold: 0.7 } } } }]);
    });

    it('loads the image prompt builder prompts and saves only the edited one', () => {
        const component = create({
            prompting: { default_negative_prompt: 'x', image_prompt_builder_system_prompt: 'Compose.', future_flag: true },
        });

        expect(component.mediaForm.get('prompting.image_prompt_builder_system_prompt')!.value).toBe('Compose.');
        component.mediaForm.get('prompting.image_prompt_builder_user_template')!.setValue('Context: {tool_context}');
        component.saveChanges();

        expect(saved).toEqual([{ synthesis: { prompting: { image_prompt_builder_user_template: 'Context: {tool_context}' } } }]);
    });

    it('does not send a request when nothing changed', () => {
        const component = create({ image_check: { ...IMAGE_CHECK_DEFAULTS } });

        component.saveChanges();

        expect(saved).toEqual([]);
    });

    it('does not save when the settings could not be loaded', () => {
        const component = create({}, throwError(() => new Error('offline')));

        control(component, 'relevance.threshold').setValue(0.7);
        component.saveChanges();

        expect(component.hasChanges()).toBeFalse();
        expect(saved).toEqual([]);
    });

    it('puts the built-in prompt back on reset', () => {
        const component = create({ image_check: { ...IMAGE_CHECK_DEFAULTS, system_prompt: 'Judge.' } });

        component.resetPrompt('image_check.system_prompt', 'synthesis.image_check.system_prompt');
        component.resetPrompt('prompting.image_prompt_builder_user_template', 'synthesis.prompting.image_prompt_builder_user_template');

        expect(control(component, 'system_prompt').value).toBe('Built-in judge.');
        expect(component.mediaForm.get('prompting.image_prompt_builder_user_template')!.value).toBe('Built-in {tool_context}');
    });
});
