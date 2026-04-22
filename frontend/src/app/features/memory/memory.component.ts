import { Component, OnInit } from '@angular/core';
import {
    MemoryEmulateHit,
    MemoryHistoryItem,
    MemoryRecord,
    MemoryTraceStep,
} from '../../core/models/memory.model';
import { MemoryService } from '../../core/services/memory.service';
import { LocalizationService } from '../../shared/pipes/translation/localization.service';

interface MemoryRecordGroup {
    dateKey: string;
    dateLabel: string;
    records: MemoryRecord[];
}

interface HistoryPair {
    id: string;
    items: MemoryHistoryItem[];
}

@Component({
    selector: 'app-memory',
    templateUrl: './memory.component.html',
    styleUrls: ['./memory.component.less'],
})
export class MemoryComponent implements OnInit {
    isLoading = false;
    isRefreshing = false;
    aiSearchStarted = false;

    activeTab: 'ai' | 'short' | 'all' = 'ai';

    aiQuery = '';
    aiMessageId = '';
    aiRecentPairs = 32;
    aiWindowPairs = 32;
    aiLookbackDays = 7;
    aiTopK = 8;
    aiTrace: MemoryTraceStep[] = [];
    aiHits: MemoryEmulateHit[] = [];

    query = '';
    messageId = '';
    days = 30;

    total = 0;
    generatedAt = '';
    records: MemoryRecord[] = [];
    groups: MemoryRecordGroup[] = [];
    allMessages: MemoryHistoryItem[] = [];
    allPairs: HistoryPair[] = [];
    allOffset = 0;
    allLimit = 32;
    allHasMore = true;
    allLoadingMore = false;

    constructor(
        private memoryService: MemoryService,
        private localizationService: LocalizationService
    ) {}

    ngOnInit(): void {
        this.localizationService.init();
    }

    setTab(tab: 'ai' | 'short' | 'all'): void {
        this.activeTab = tab;
        if (tab === 'short' && !this.records.length) {
            this.loadRecent();
        }
        if (tab === 'all' && !this.allMessages.length) {
            this.loadAllMessages(true);
        }
    }

    loadRecent(): void {
        this.isLoading = true;
        this.memoryService.listShortTerm$(this.days).subscribe((response) => {
            this.records = response?.records || [];
            this.total = Number(response?.total || 0);
            this.generatedAt = '';
            this.rebuildGroups();
            this.isLoading = false;
        });
    }

    runSearch(): void {
        this.isLoading = true;
        this.memoryService
            .search$(this.query, this.messageId, this.days, 80)
            .subscribe((response) => {
                this.records = response?.records || [];
                this.total = Number(response?.total || 0);
                this.generatedAt = response?.generated_at
                    ? this.formatDateTime(response.generated_at)
                    : '';
                this.rebuildGroups();
                this.isLoading = false;
            });
    }

    runAiSearch(): void {
        this.aiSearchStarted = true;
        this.isLoading = true;
        this.memoryService
            .emulateSearch$({
                q: this.aiQuery,
                messageId: this.aiMessageId,
                recentPairs: this.aiRecentPairs,
                windowPairs: this.aiWindowPairs,
                lookbackDays: this.aiLookbackDays,
                topK: this.aiTopK,
            })
            .subscribe((response) => {
                this.aiTrace = response?.trace || [];
                this.aiHits = response?.hits || [];
                this.total = this.aiHits.length;
                this.generatedAt = this.formatDateTime(new Date().toISOString());
                this.isLoading = false;
            });
    }

    resetFilters(): void {
        this.query = '';
        this.messageId = '';
        this.loadRecent();
    }

    resetAiFilters(): void {
        this.aiQuery = '';
        this.aiMessageId = '';
        this.aiRecentPairs = 32;
        this.aiWindowPairs = 32;
        this.aiLookbackDays = 7;
        this.aiTopK = 8;
        if (this.aiSearchStarted) {
            this.runAiSearch();
            return;
        }
        this.aiTrace = [];
        this.aiHits = [];
        this.total = 0;
        this.generatedAt = '';
    }

    refreshMemories(): void {
        if (this.isRefreshing) {
            return;
        }
        this.isRefreshing = true;
        this.memoryService.refresh$(this.days).subscribe(() => {
            this.isRefreshing = false;
            if (this.activeTab === 'ai') {
                if (this.aiSearchStarted) {
                    this.runAiSearch();
                }
                return;
            }
            if (this.activeTab === 'all') {
                this.loadAllMessages(true);
                return;
            }
            this.runSearchIfNeeded();
        });
    }

    onAllMessagesScroll(event: Event): void {
        const target = event.target as HTMLElement | null;
        if (!target || this.allLoadingMore || !this.allHasMore) {
            return;
        }
        const threshold = 120;
        const nearBottom = target.scrollTop + target.clientHeight >= target.scrollHeight - threshold;
        if (nearBottom) {
            this.loadAllMessages(false);
        }
    }

    formatDateTime(value: string | null | undefined): string {
        if (!value) {
            return '';
        }
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return value;
        }
        return new Intl.DateTimeFormat(this.localizationService.currentLang() || 'ru-RU', {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        }).format(parsed);
    }

    trackByRecord(_index: number, record: MemoryRecord): string {
        return record.id;
    }

    trackByAiHit(_index: number, hit: MemoryEmulateHit): string {
        return hit.id;
    }

    trackByAllPair(_index: number, pair: HistoryPair): string {
        return pair.id;
    }

    private runSearchIfNeeded(): void {
        if (this.query.trim() || this.messageId.trim()) {
            this.runSearch();
            return;
        }
        this.loadRecent();
    }

    private rebuildGroups(): void {
        const locale = this.localizationService.currentLang() || 'ru-RU';
        const map = new Map<string, MemoryRecordGroup>();

        for (const record of this.records) {
            const sourceDate = record.updated_at || record.created_at || '';
            const parsed = sourceDate ? new Date(sourceDate) : null;
            const dateKey = parsed && !Number.isNaN(parsed.getTime())
                ? parsed.toISOString().slice(0, 10)
                : 'unknown';
            const dateLabel = parsed && !Number.isNaN(parsed.getTime())
                ? new Intl.DateTimeFormat(locale, {
                    day: '2-digit',
                    month: 'long',
                    year: 'numeric',
                }).format(parsed)
                : 'Unknown date';

            const existing = map.get(dateKey);
            if (existing) {
                existing.records.push(record);
            } else {
                map.set(dateKey, {
                    dateKey,
                    dateLabel,
                    records: [record],
                });
            }
        }

        this.groups = Array.from(map.values());
    }

    private loadAllMessages(reset: boolean): void {
        if (this.allLoadingMore) {
            return;
        }
        if (reset) {
            this.isLoading = true;
            this.allMessages = [];
            this.allPairs = [];
            this.allOffset = 0;
            this.allHasMore = true;
        }
        if (!this.allHasMore && !reset) {
            return;
        }

        this.allLoadingMore = true;
        this.memoryService.listHistory$(this.allLimit, this.allOffset).subscribe((response) => {
            const chunk = response?.records || [];
            this.allMessages = [...this.allMessages, ...chunk];
            this.allOffset += chunk.length;
            this.allHasMore = Boolean(response?.has_more);
            this.total = this.allMessages.length;
            this.rebuildAllPairs();

            this.allLoadingMore = false;
            this.isLoading = false;
        });
    }

    private rebuildAllPairs(): void {
        const pairs: HistoryPair[] = [];
        for (let i = 0; i < this.allMessages.length; i += 2) {
            const slice = this.allMessages.slice(i, i + 2);
            if (!slice.length) {
                continue;
            }
            const id = `${slice.map((entry) => entry.id).join('_')}_${i}`;
            pairs.push({ id, items: slice });
        }
        this.allPairs = pairs;
    }
}
