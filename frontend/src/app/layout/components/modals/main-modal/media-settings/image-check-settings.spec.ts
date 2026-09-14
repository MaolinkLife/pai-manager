import {
    canRegenerate,
    clampGenerations,
    clampThreshold,
    generationsWarning,
    IMAGE_CHECK_DEFAULTS,
    normalizeImageCheck,
} from './image-check-settings';

describe('image check settings', () => {
    it('keeps a threshold between 0.10 and 1.00 with two decimals', () => {
        expect(clampThreshold(0.01, 0.6)).toBe(0.1);
        expect(clampThreshold(7, 0.6)).toBe(1);
        expect(clampThreshold('0.456', 0.6)).toBe(0.46);
        expect(clampThreshold(null, 0.6)).toBe(0.6);
        expect(clampThreshold('abc', 0.82)).toBe(0.82);
    });

    it('keeps the generation count a whole number from 1 to 10', () => {
        expect(clampGenerations(0)).toBe(1);
        expect(clampGenerations(99)).toBe(10);
        expect(clampGenerations(2.6)).toBe(3);
        expect(clampGenerations('')).toBe(2);
    });

    it('fills a missing or partial config with the owner defaults', () => {
        expect(normalizeImageCheck(undefined)).toEqual(IMAGE_CHECK_DEFAULTS);
        expect(normalizeImageCheck({ quality: { enabled: true } }).quality).toEqual({
            enabled: true,
            threshold: 0.82,
            reroll: false,
        });
    });

    it('regenerates only when an enabled check may request a new image', () => {
        const quality = { enabled: false, threshold: 0.82, reroll: true };
        expect(canRegenerate({ ...IMAGE_CHECK_DEFAULTS, quality })).toBeFalse();
        expect(canRegenerate({ ...IMAGE_CHECK_DEFAULTS, quality: { ...quality, enabled: true } })).toBeTrue();
        expect(canRegenerate(IMAGE_CHECK_DEFAULTS)).toBeFalse();
    });

    it('warns above three generations', () => {
        expect(generationsWarning(3)).toBeFalse();
        expect(generationsWarning(4)).toBeTrue();
    });
});
