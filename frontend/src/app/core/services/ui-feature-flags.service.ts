import { Injectable } from '@angular/core';
import { environment } from '../../../environments/environment';

export type UiFeatureKey = 'audit' | 'diary' | 'tasks';

export interface UiFeatureFlags {
    audit: boolean;
    diary: boolean;
    tasks: boolean;
}

const DEFAULT_UI_FEATURE_FLAGS: UiFeatureFlags = {
    audit: false,
    diary: false,
    tasks: false,
};

@Injectable({
    providedIn: 'root',
})
export class UiFeatureFlagsService {
    private readonly flags: UiFeatureFlags;

    constructor() {
        this.flags = this.resolveFlags();
    }

    isEnabled(key: UiFeatureKey): boolean {
        return Boolean(this.flags[key]);
    }

    all(): UiFeatureFlags {
        return { ...this.flags };
    }

    private resolveFlags(): UiFeatureFlags {
        const envFlags = ((environment as any).uiFeatures || {}) as Partial<UiFeatureFlags>;
        const storageFlags = this.readStorageFlags();
        const forceDiary = typeof envFlags.diary === 'boolean' ? envFlags.diary : undefined;

        const merged: UiFeatureFlags = {
            ...DEFAULT_UI_FEATURE_FLAGS,
            ...storageFlags,
            ...envFlags,
        };
        if (typeof forceDiary === 'boolean') {
            merged.diary = forceDiary;
        }
        return merged;
    }

    private readStorageFlags(): Partial<UiFeatureFlags> {
        try {
            const raw = localStorage.getItem('ui.features');
            if (!raw) {
                return {};
            }

            const parsed = JSON.parse(raw) as Partial<UiFeatureFlags>;
            return {
                audit: typeof parsed.audit === 'boolean' ? parsed.audit : undefined,
                diary: typeof parsed.diary === 'boolean' ? parsed.diary : undefined,
                tasks: typeof parsed.tasks === 'boolean' ? parsed.tasks : undefined,
            };
        } catch {
            return {};
        }
    }
}
