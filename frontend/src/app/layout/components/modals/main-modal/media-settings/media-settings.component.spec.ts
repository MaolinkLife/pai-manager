import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { IMAGE_CHECK_DEFAULTS } from './image-check-settings';
import { MediaSettingsComponent } from './media-settings.component';

const BUILT_IN: Record<string, string> = {
    'synthesis.image_check.system_prompt': 'Built-in judge.',
    'synthesis.prompting.image_prompt_builder_user_template': 'Built-in {tool_context}',
};

describe('MediaSettingsComponent image check', () => {
    let saved: any[];

    function create(synthesis: any): MediaSettingsComponent {
        saved = [];
        const configService: any = {
            getConfig$: () => of({ synthesis }),
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

    it('falls back to the owner defaults when the config has no check', () => {
        const component = create({});

        expect(component.mediaForm.getRawValue().image_check).toEqual(IMAGE_CHECK_DEFAULTS);
    });

    it('saves the check in range, with locked values and keys the form does not know', () => {
        const component = create({
            image_check: { ...IMAGE_CHECK_DEFAULTS, system_prompt: 'Judge.', future_flag: true },
        });

        control(component, 'relevance.reroll').setValue(true);
        control(component, 'relevance.threshold').setValue(0.567);
        control(component, 'max_generations').setValue(99);
        component.saveChanges();

        expect(saved.length).toBe(1);
        expect(saved[0].synthesis.image_check).toEqual({
            future_flag: true,
            relevance: { enabled: true, threshold: 0.57, reroll: true },
            quality: { enabled: false, threshold: 0.82, reroll: false },
            max_generations: 10,
            describe_prompt: '',
            system_prompt: 'Judge.',
            user_template: '',
        });
    });

    it('loads and saves the scene answer format with keys the form does not know', () => {
        const component = create({ image_scene: { format_prompt: 'Return JSON.', future_flag: true } });

        expect(component.mediaForm.get('image_scene.format_prompt')!.value).toBe('Return JSON.');
        component.mediaForm.get('image_scene.format_prompt')!.setValue('Return strict JSON.');
        component.saveChanges();

        expect(saved[0].synthesis.image_scene).toEqual({ format_prompt: 'Return strict JSON.', future_flag: true });
    });

    it('has no old assessment fields and keeps the hidden prompt-engineering switch', () => {
        const component = create({ prompting: { enabled: false, default_negative_prompt: 'x' } });

        ['assess_enabled', 'quality_threshold', 'max_attempts', 'retry_enabled', 'enabled'].forEach((key) => {
            expect(component.mediaForm.get(`prompting.${key}`)).withContext(key).toBeNull();
        });

        control(component, 'relevance.threshold').setValue(0.7);
        component.saveChanges();

        const prompting = saved[0].synthesis.prompting;
        expect(prompting.enabled).toBeFalse();
        expect('assess_enabled' in prompting).toBeFalse();
    });

    it('loads and saves the image prompt builder prompts with the rest of prompting', () => {
        const component = create({
            prompting: { default_negative_prompt: 'x', image_prompt_builder_system_prompt: 'Compose.', future_flag: true },
        });

        expect(component.mediaForm.get('prompting.image_prompt_builder_system_prompt')!.value).toBe('Compose.');
        component.mediaForm.get('prompting.image_prompt_builder_user_template')!.setValue('Context: {tool_context}');
        component.saveChanges();

        const prompting = saved[0].synthesis.prompting;
        expect(prompting.image_prompt_builder_system_prompt).toBe('Compose.');
        expect(prompting.image_prompt_builder_user_template).toBe('Context: {tool_context}');
        expect(prompting.future_flag).toBeTrue();
    });

    it('puts the built-in prompt back on reset', () => {
        const component = create({ image_check: { ...IMAGE_CHECK_DEFAULTS, system_prompt: 'Judge.' } });

        component.resetPrompt('image_check.system_prompt', 'synthesis.image_check.system_prompt');
        component.resetPrompt('prompting.image_prompt_builder_user_template', 'synthesis.prompting.image_prompt_builder_user_template');

        expect(control(component, 'system_prompt').value).toBe('Built-in judge.');
        expect(component.mediaForm.get('prompting.image_prompt_builder_user_template')!.value).toBe('Built-in {tool_context}');
    });
});
