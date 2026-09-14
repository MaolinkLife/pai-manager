import {
    SynthesisImageCheckConfig,
    SynthesisImageCheckGateConfig,
} from '../../../../../core/models/project-config.model';

// Checking a generated image: vision describes the
// result, a judge scores it against the request; below a threshold the image is
// still delivered unless a check may request a new one. The backend reads the
// same shape from `synthesis.image_check`.

export const IMAGE_CHECK_THRESHOLD = { min: 0.1, max: 1, step: 0.01 } as const;
export const IMAGE_CHECK_GENERATIONS = { min: 1, max: 10, warnAbove: 3 } as const;
export const IMAGE_CHECK_GATES = ['relevance', 'quality'] as const;
export type ImageCheckGateName = typeof IMAGE_CHECK_GATES[number];

// Empty prompts mean the built-in ones on the backend.
export const IMAGE_CHECK_DEFAULTS: SynthesisImageCheckConfig = {
    relevance: { enabled: true, threshold: 0.6, reroll: false },
    quality: { enabled: false, threshold: 0.82, reroll: false },
    max_generations: 2,
    describe_prompt: '',
    system_prompt: '',
    user_template: '',
};

export function clampThreshold(value: unknown, fallback: number): number {
    const number = Number(value);
    if (value === null || value === '' || !Number.isFinite(number)) {
        return fallback;
    }
    const clamped = Math.min(IMAGE_CHECK_THRESHOLD.max, Math.max(IMAGE_CHECK_THRESHOLD.min, number));
    return Math.round(clamped * 100) / 100;
}

export function clampGenerations(value: unknown, fallback: number = IMAGE_CHECK_DEFAULTS.max_generations): number {
    const number = Number(value);
    if (value === null || value === '' || !Number.isFinite(number)) {
        return fallback;
    }
    return Math.min(IMAGE_CHECK_GENERATIONS.max, Math.max(IMAGE_CHECK_GENERATIONS.min, Math.round(number)));
}

export function normalizeImageCheck(raw: any): SynthesisImageCheckConfig {
    const source = raw && typeof raw === 'object' ? raw : {};
    const gate = (name: ImageCheckGateName): SynthesisImageCheckGateConfig => {
        const defaults = IMAGE_CHECK_DEFAULTS[name];
        const value = source[name] && typeof source[name] === 'object' ? source[name] : {};
        return {
            enabled: typeof value.enabled === 'boolean' ? value.enabled : defaults.enabled,
            threshold: clampThreshold(value.threshold, defaults.threshold),
            reroll: typeof value.reroll === 'boolean' ? value.reroll : defaults.reroll,
        };
    };
    const text = (value: unknown): string => (typeof value === 'string' ? value : '');
    return {
        relevance: gate('relevance'),
        quality: gate('quality'),
        max_generations: clampGenerations(source.max_generations),
        describe_prompt: text(source.describe_prompt),
        system_prompt: text(source.system_prompt),
        user_template: text(source.user_template),
    };
}

/** More than one generation happens only when an enabled check may request a new image. */
export function canRegenerate(check: SynthesisImageCheckConfig): boolean {
    return IMAGE_CHECK_GATES.some((name) => check[name].enabled && check[name].reroll);
}

export function generationsWarning(count: unknown): boolean {
    return Number(count) > IMAGE_CHECK_GENERATIONS.warnAbove;
}
