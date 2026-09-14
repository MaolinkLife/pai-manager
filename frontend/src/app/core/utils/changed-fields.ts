const isPlainObject = (value: unknown): value is Record<string, unknown> =>
    typeof value === 'object' && value !== null && !Array.isArray(value);

/**
 * A settings save sends only the fields it changed.
 *
 * Compares a form value with the value it was loaded from and returns the changed
 * leaves in the same shape. Plain objects are walked; anything else (numbers,
 * strings, arrays) is compared as a whole. Nothing changed → an empty object.
 */
export const pickChangedFields = (current: unknown, original: unknown): Record<string, unknown> => {
    const changes: Record<string, unknown> = {};
    if (!isPlainObject(current)) {
        return changes;
    }
    const base = isPlainObject(original) ? original : {};
    Object.keys(current).forEach((key) => {
        const value = current[key];
        if (isPlainObject(value)) {
            const nested = pickChangedFields(value, base[key]);
            if (Object.keys(nested).length > 0) {
                changes[key] = nested;
            }
        } else if (JSON.stringify(value) !== JSON.stringify(base[key])) {
            changes[key] = value;
        }
    });
    return changes;
};
