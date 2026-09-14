import { ModelIndexEntry } from '../services/api.service';
import { UiSelectOption } from '../../shared/ui/components/ui-select/ui-select.component';

export interface ModelOptionLabels {
    /** Shown as the only, disabled option when no model can do the capability. */
    noModels: string;
    /** "no mark" note for a chosen model that is indexed without the capability. */
    notMarked: string;
    /** Note for a chosen model the index does not know. */
    notIndexed: string;
    /** The capability's own label, e.g. "vision". */
    capability: string;
}

/** The labels for `buildModelOptions`, translated. */
export const modelOptionLabels = (t: (key: string) => string, capability: string): ModelOptionLabels => ({
    noModels: t('settingsPage.models.optionsNoModels'),
    notMarked: t('settingsPage.models.optionsNotMarked'),
    notIndexed: t('settingsPage.models.optionsNotIndexed'),
    capability: t(`settingsPage.models.capabilities.${capability}`),
});

/**
 * The models a picker offers: only those the model index says can do `capability`.
 * The model already chosen stays in the list with a note when
 * it cannot, so a setting is never changed silently.
 */
export const buildModelOptions = (
    entries: readonly ModelIndexEntry[] | null | undefined,
    capability: string,
    current: string | null | undefined,
    labels: ModelOptionLabels,
    options: { placeholderWhenEmpty?: boolean } = {},
): UiSelectOption<string>[] => {
    const index = entries ?? [];
    const result: UiSelectOption<string>[] = index
        .filter((entry) => entry.capabilities.includes(capability))
        .map((entry) => ({ value: entry.name, label: entry.name }));

    const chosen = String(current ?? '').trim();
    if (chosen && !result.some((option) => option.value === chosen)) {
        const indexed = index.some((entry) => entry.name === chosen);
        const note = indexed ? `${labels.notMarked}: ${labels.capability}` : labels.notIndexed;
        result.unshift({ value: chosen, label: `${chosen} — ${note}` });
    }

    if (!result.length && options.placeholderWhenEmpty !== false) {
        return [{ value: '', label: labels.noModels, disabled: true }];
    }
    return result;
};

/** Names of the models that can do `capability`, for pickers that list plain names. */
export const modelNamesWith = (entries: readonly ModelIndexEntry[] | null | undefined, capability: string): string[] =>
    (entries ?? []).filter((entry) => entry.capabilities.includes(capability)).map((entry) => entry.name);
