import { Component, OnInit } from '@angular/core';
import { UiFeatureFlagsService } from '../../core/services/ui-feature-flags.service';
import { DiaryEntryDto, DiaryListResponse, DiaryService } from '../../core/services/diary.service';

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
    id: string;
    date: string;
    mood: string;
    summary: string;
    narrative: string;
    selfReflection: string;
    tags: string[];
    structured: DiaryStructuredPayload | null;
    // Hidden by sleep consolidation (payload.pruned); shown only on request.
    hidden: boolean;
    hiddenReason: string;
}

const KNOWN_HIDDEN_REASONS = new Set(['low_importance', 'superseded_by', 'user_archived']);

@Component({
    selector: 'app-diary',
    templateUrl: './diary.component.html',
    styleUrls: ['./diary.component.less'],
    standalone: false
})
export class DiaryComponent implements OnInit {
    readonly featureEnabled: boolean;
    readonly pageSize = 30;
    loading = false;
    loadingMore = false;
    generating = false;
    error = '';
    hasMore = false;
    showHidden = false;

    entries: DiaryEntry[] = [];

    // A page that arrives after a reload (refresh, hidden switch) is dropped.
    private loadRequest = 0;

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

    setShowHidden(show: boolean): void {
        if (this.showHidden === show) {
            return;
        }
        this.showHidden = show;
        this.loadEntries();
    }

    loadMore(): void {
        if (this.loading || this.loadingMore || !this.hasMore) {
            return;
        }
        const request = this.loadRequest;
        this.loadingMore = true;
        this.error = '';
        this.diaryService.getEntries$(this.entries.length, this.pageSize, this.showHidden).subscribe({
            next: (response) => {
                if (request !== this.loadRequest) {
                    return;
                }
                this.entries = this.entries.concat(this.mapRows(response));
                this.hasMore = !!response?.has_more;
                this.loadingMore = false;
            },
            error: () => {
                if (request !== this.loadRequest) {
                    return;
                }
                this.loadingMore = false;
                this.error = 'Failed to load diary entries';
            },
        });
    }

    hiddenReasonKey(reason: string): string | null {
        return KNOWN_HIDDEN_REASONS.has(reason) ? `diary.hiddenReasons.${reason}` : null;
    }

    trackEntry(_index: number, entry: DiaryEntry): string {
        return entry.id || entry.date;
    }

    private loadEntries(): void {
        const request = ++this.loadRequest;
        this.loading = true;
        this.loadingMore = false;
        this.error = '';
        this.diaryService.getEntries$(0, this.pageSize, this.showHidden).subscribe({
            next: (response) => {
                if (request !== this.loadRequest) {
                    return;
                }
                this.entries = this.mapRows(response);
                this.hasMore = !!response?.has_more;
                this.loading = false;
            },
            error: () => {
                if (request !== this.loadRequest) {
                    return;
                }
                this.loading = false;
                this.hasMore = false;
                this.error = 'Failed to load diary entries';
            },
        });
    }

    private mapRows(response: DiaryListResponse | null | undefined): DiaryEntry[] {
        const rows = Array.isArray(response?.entries) ? response!.entries : [];
        return rows.map((row) => this.mapEntry(row));
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
        const pruned = payload?.['pruned'] && typeof payload['pruned'] === 'object'
            ? payload['pruned'] as Record<string, any>
            : null;
        const hiddenReason = pruned ? String(pruned['reason'] || '').trim() : '';
        return {
            id: row.id || '',
            date: row.day || row.updated_at || new Date().toISOString(),
            mood: row.mood || 'Neutral',
            summary: row.summary || '',
            narrative,
            selfReflection,
            tags: Array.isArray(row.tags) ? row.tags : [],
            structured: structuredRaw ? this.mapStructured(structuredRaw) : null,
            hidden: !!hiddenReason,
            hiddenReason,
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
