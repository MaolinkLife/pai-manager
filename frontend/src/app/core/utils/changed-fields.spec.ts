import { pickChangedFields } from './changed-fields';

describe('pickChangedFields', () => {
    const original = { enabled: false, chat: { enabled: true }, selfie: { enabled: true, chance: 0.4 }, tags: ['a'] };

    it('returns only the changed leaves, keeping their nesting', () => {
        const current = { ...original, selfie: { enabled: true, chance: 0.7 } };

        expect(pickChangedFields(current, original)).toEqual({ selfie: { chance: 0.7 } });
    });

    it('returns an empty object when nothing changed', () => {
        expect(pickChangedFields(JSON.parse(JSON.stringify(original)), original)).toEqual({});
    });

    it('compares arrays as a whole value', () => {
        expect(pickChangedFields({ ...original, tags: ['a', 'b'] }, original)).toEqual({ tags: ['a', 'b'] });
    });
});
