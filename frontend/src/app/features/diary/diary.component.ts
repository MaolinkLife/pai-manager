import { Component, OnInit } from '@angular/core';
import { UiFeatureFlagsService } from '../../core/services/ui-feature-flags.service';
import { DiaryEntryDto, DiaryService } from '../../core/services/diary.service';

interface DiaryStructuredEmotion {
    valence: string;
    arousal: string;
    notes: string;
}

interface DiaryStructuredPayload {
    title: string;
    source_event: string;
    outcomes: string[];
    entities: string[];
    key_messages: string[];
    importance_score: number | null;
    importance_notes: string;
    emotion: DiaryStructuredEmotion | null;
    relationships: string;
    retrieval_cues: string[];
    similarities: string[];
    photo_descriptions: string[];
    contradictions: string[];
}

interface DiaryEntry {
    date: string;
    mood: string;
    summary: string;
    narrative: string;
    selfReflection: string;
    tags: string[];
    structured: DiaryStructuredPayload | null;
}

@Component({
    selector: 'app-diary',
    templateUrl: './diary.component.html',
    styleUrls: ['./diary.component.less'],
})
export class DiaryComponent implements OnInit {
    readonly featureEnabled: boolean;
    loading = false;
    generating = false;
    error = '';

    entries: DiaryEntry[] = [];

    constructor(
        uiFeatureFlags: UiFeatureFlagsService,
        private diaryService: DiaryService,
    ) {
        this.featureEnabled = uiFeatureFlags.isEnabled('diary');
    }

    ngOnInit(): void {
        if (!this.featureEnabled) {
            return;
        }
        this.loadEntries();
    }

    refreshEntries(): void {
        this.loadEntries();
    }

    generateDailyEntry(): void {
        this.generating = true;
        this.error = '';
        this.diaryService.generateEntry$(undefined, true).subscribe({
            next: () => {
                this.generating = false;
                this.loadEntries();
            },
            error: () => {
                this.generating = false;
                this.error = 'Failed to generate diary entry';
            },
        });
    }

    private loadEntries(): void {
        this.loading = true;
        this.error = '';
        this.diaryService.getEntries$(30).subscribe({
            next: (response) => {
                const rows = Array.isArray(response?.entries) ? response.entries : [];
                this.entries = rows.map((row) => this.mapEntry(row));
                this.loading = false;
            },
            error: () => {
                this.loading = false;
                this.error = 'Failed to load diary entries';
            },
        });
    }

    private mapEntry(row: DiaryEntryDto): DiaryEntry {
        const payload = row?.payload && typeof row.payload === 'object' ? row.payload : {};
        const structuredRaw = payload?.['structured'] && typeof payload['structured'] === 'object'
            ? payload['structured'] as Record<string, any>
            : null;
        const narrative = typeof payload?.['narrative'] === 'string'
            ? String(payload['narrative']).trim()
            : '';
        const selfReflection = typeof payload?.['self_reflection'] === 'string'
            ? String(payload['self_reflection']).trim()
            : '';
        return {
            date: row.day || row.updated_at || new Date().toISOString(),
            mood: row.mood || 'Neutral',
            summary: row.summary || '',
            narrative,
            selfReflection,
            tags: Array.isArray(row.tags) ? row.tags : [],
            structured: structuredRaw ? this.mapStructured(structuredRaw) : null,
        };
    }

    private mapStructured(payload: Record<string, any>): DiaryStructuredPayload {
        const emotionRaw = payload?.['emotion'] && typeof payload['emotion'] === 'object'
            ? payload['emotion'] as Record<string, any>
            : null;
        return {
            title: String(payload['title'] || '').trim(),
            source_event: String(payload['source_event'] || '').trim(),
            outcomes: this.asStringList(payload['outcomes']),
            entities: this.asStringList(payload['entities']),
            key_messages: this.asStringList(payload['key_messages']),
            importance_score: this.asNullableNumber(payload['importance_score']),
            importance_notes: String(payload['importance_notes'] || '').trim(),
            emotion: emotionRaw ? {
                valence: String(emotionRaw['valence'] || '').trim(),
                arousal: String(emotionRaw['arousal'] || '').trim(),
                notes: String(emotionRaw['notes'] || '').trim(),
            } : null,
            relationships: String(payload['relationships'] || '').trim(),
            retrieval_cues: this.asStringList(payload['retrieval_cues']),
            similarities: this.asStringList(payload['similarities']),
            photo_descriptions: this.asStringList(payload['photo_descriptions']),
            contradictions: this.asStringList(payload['contradictions']),
        };
    }

    private asStringList(value: any): string[] {
        return Array.isArray(value)
            ? value.map((item) => String(item || '').trim()).filter(Boolean)
            : [];
    }

    private asNullableNumber(value: any): number | null {
        const numeric = Number(value);
        return Number.isFinite(numeric) ? numeric : null;
    }
}
