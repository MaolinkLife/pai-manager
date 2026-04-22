import { Injectable, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';

@Injectable({
    providedIn: 'root'
})
export class LocalizationService {
    private readonly translations = signal<Record<string, unknown>>({});
    readonly translationsState = this.translations.asReadonly();
    readonly currentLang = signal<string>('ru-RU');
    private readonly cacheBuster = Date.now();

    constructor(private http: HttpClient) { }

    setLanguage(lang: string, forceReload = false) {
        const normalizedLang = this.normalizeLanguage(lang);
        if (!forceReload && this.currentLang() === normalizedLang && Object.keys(this.translations()).length > 0) {
            return;
        }
        this.currentLang.set(normalizedLang);
        localStorage.setItem('language', normalizedLang);
        this.loadTranslations(normalizedLang);
    }

    t(key: string): string {
        const keys = key.split('.');
        let value: unknown = this.translations();

        for (const k of keys) {
            if (value && typeof value === 'object' && k in value) {
                value = (value as Record<string, unknown>)[k];
            } else {
                return key;
            }
        }

        return typeof value === 'string' ? value : key;
    }

    private loadTranslations(lang: string) {
        const candidates = this.translationCandidates(lang);
        const tryLoad = (index: number) => {
            if (index >= candidates.length) {
                console.error(`Failed to load translations for ${lang}`);
                return;
            }

            const candidate = candidates[index];
            this.http.get<Record<string, unknown>>(`/assets/i18n/${candidate}.json?v=${this.cacheBuster}`).subscribe(
                (data) => this.translations.set(data),
                () => tryLoad(index + 1)
            );
        };

        tryLoad(0);
    }

    init() {
        const saved = localStorage.getItem('language') || 'ru-RU';
        this.setLanguage(saved, true);
    }

    private normalizeLanguage(lang: string): string {
        const value = (lang || '').trim();
        const lower = value.toLowerCase();
        if (lower === 'ru' || lower === 'ru-ru') {
            return 'ru-RU';
        }
        if (lower === 'en' || lower === 'en-us' || lower === 'en-gb') {
            return 'en-US';
        }
        return value || 'ru-RU';
    }

    private translationCandidates(lang: string): string[] {
        const normalized = this.normalizeLanguage(lang);
        const short = normalized.split('-')[0];
        const fallback = normalized.startsWith('ru') ? 'ru-RU' : 'en-US';
        return Array.from(new Set([normalized, short, fallback]));
    }
}
