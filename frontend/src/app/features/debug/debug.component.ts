import { AfterViewInit, Component, ElementRef, HostListener, OnInit, ViewChild } from '@angular/core';
import { LoggerService } from '../../core/services/logger.service';
import { DebugVaultEntry, DebugVaultService } from '../../core/services/debug-vault.service';

const TAG_RE = /\[([^\]]+)\]/g;
const JSON_LIKE_RE = /^\s*[\[{]/;

@Component({
    selector: 'app-debug',
    templateUrl: './debug.component.html',
    styleUrls: ['./debug.component.less'],
})
export class DebugComponent implements OnInit, AfterViewInit {
    private readonly PAGE_SIZE = 30;
    private readonly SCROLL_THRESHOLD_PX = 260;

    logs: any[] = [];
    filteredLogs: any[] = [];
    visibleLogs: any[] = [];
    isLoadingMore = false;
    isInitialLoading = false;
    hasMoreLogs = false;
    currentSessionId = '';
    private visibleCount = this.PAGE_SIZE;

    expandedLogs: Set<number> = new Set();
    @ViewChild('debugLogContainer') debugLogContainer?: ElementRef<HTMLElement>;

    availableSources: string[] = [];
    activeSources: string[] = [];
    availableStatuses: string[] = [];
    activeStatuses: string[] = [];

    // DebugVault tab (0.9.x P10-B)
    activeTab: 'logs' | 'vault' = 'logs';
    vaultEntries: DebugVaultEntry[] = [];
    vaultTotal = 0;
    vaultOffset = 0;
    readonly vaultPageSize = 25;
    vaultLoading = false;
    vaultKinds: string[] = [];
    vaultKindFilter = '';
    vaultReviewedFilter: 'all' | 'reviewed' | 'unreviewed' = 'all';
    vaultExpanded: Set<string> = new Set();
    vaultReviewNotes: Record<string, string> = {};
    vaultReviewBusy: Set<string> = new Set();

    constructor(
        private loggerService: LoggerService,
        private debugVaultService: DebugVaultService,
    ) {}

    ngOnInit(): void {
        this.loadAllLogs();
    }

    selectTab(tab: 'logs' | 'vault'): void {
        this.activeTab = tab;
        if (tab === 'vault' && !this.vaultEntries.length && !this.vaultLoading) {
            this.loadVault(true);
        }
    }

    loadVault(reset = false): void {
        if (reset) {
            this.vaultOffset = 0;
            this.vaultEntries = [];
            this.vaultExpanded.clear();
        }
        this.vaultLoading = true;
        const reviewed =
            this.vaultReviewedFilter === 'all'
                ? undefined
                : this.vaultReviewedFilter === 'reviewed';
        this.debugVaultService
            .list$({
                kind: this.vaultKindFilter || undefined,
                reviewed,
                limit: this.vaultPageSize,
                offset: this.vaultOffset,
            })
            .subscribe({
                next: (response) => {
                    const incoming = response?.entries || [];
                    this.vaultEntries = reset
                        ? incoming
                        : [...this.vaultEntries, ...incoming];
                    this.vaultTotal = response?.total ?? this.vaultEntries.length;
                    this.vaultOffset = this.vaultEntries.length;
                    this.collectVaultKinds(incoming);
                    this.vaultLoading = false;
                },
                error: () => {
                    this.vaultLoading = false;
                },
            });
    }

    get vaultHasMore(): boolean {
        return this.vaultEntries.length < this.vaultTotal;
    }

    onVaultFilterChanged(): void {
        this.loadVault(true);
    }

    toggleVaultEntry(entryId: string): void {
        if (this.vaultExpanded.has(entryId)) {
            this.vaultExpanded.delete(entryId);
        } else {
            this.vaultExpanded.add(entryId);
        }
    }

    markVaultReviewed(entry: DebugVaultEntry): void {
        if (this.vaultReviewBusy.has(entry.id)) {
            return;
        }
        this.vaultReviewBusy.add(entry.id);
        const note = (this.vaultReviewNotes[entry.id] || '').trim() || undefined;
        this.debugVaultService.markReviewed$(entry.id, note).subscribe({
            next: () => {
                entry.reviewed = true;
                entry.reviewed_note = note || entry.reviewed_note;
                entry.reviewed_at = new Date().toISOString();
                this.vaultReviewBusy.delete(entry.id);
                delete this.vaultReviewNotes[entry.id];
            },
            error: () => {
                this.vaultReviewBusy.delete(entry.id);
            },
        });
    }

    formatVaultJson(value: any): string {
        if (value === null || value === undefined) {
            return '';
        }
        try {
            return JSON.stringify(value, null, 2);
        } catch {
            return String(value);
        }
    }

    private collectVaultKinds(entries: DebugVaultEntry[]): void {
        const kinds = new Set(this.vaultKinds);
        for (const entry of entries) {
            if (entry.kind) {
                kinds.add(entry.kind);
            }
        }
        this.vaultKinds = Array.from(kinds).sort();
    }

    ngAfterViewInit(): void {
        setTimeout(() => this.ensureViewportFilled(), 0);
    }

    @HostListener('window:scroll')
    onWindowScroll(): void {
        this.tryExtendVisibleWindow();
    }

    onLogScroll(container: HTMLElement): void {
        const remaining = container.scrollHeight - (container.scrollTop + container.clientHeight);
        if (remaining <= this.SCROLL_THRESHOLD_PX) {
            this.extendVisibleWindow();
        }
    }

    // Server-side paging (0.9.x P10-C): with the DB-backed store a 24/7
    // session can hold tens of thousands of rows — never fetch unbounded.
    private readonly SERVER_PAGE_SIZE = 500;
    private serverOffset = 0;
    private serverHasMore = false;
    private serverLoading = false;
    serverTotal = 0;

    private loadAllLogs(): void {
        this.isInitialLoading = true;
        this.serverOffset = 0;
        this.loggerService.getDebugLogPage$(this.SERVER_PAGE_SIZE, 0, this.currentSessionId || undefined).subscribe({
            next: (response: any) => {
                this.logs = (response?.logs || []).map((l: any) => this.enrichLog(l));
                this.currentSessionId = String(response?.session_id || this.currentSessionId || '');
                this.serverOffset = this.logs.length;
                this.serverTotal = Number(response?.total ?? this.logs.length);
                this.serverHasMore = !!response?.has_more;
                this.rebuildAvailableFilters();
                this.applyFilters();
            },
            error: () => {
                this.logs = [];
                this.filteredLogs = [];
                this.visibleLogs = [];
                this.hasMoreLogs = false;
                this.serverHasMore = false;
            },
            complete: () => {
                this.isInitialLoading = false;
                setTimeout(() => this.ensureViewportFilled(), 0);
            },
        });
    }

    private loadNextServerPage(): void {
        if (!this.serverHasMore || this.serverLoading) {
            return;
        }
        this.serverLoading = true;
        this.isLoadingMore = true;
        this.loggerService
            .getDebugLogPage$(this.SERVER_PAGE_SIZE, this.serverOffset, this.currentSessionId || undefined)
            .subscribe({
                next: (response: any) => {
                    const incoming = (response?.logs || []).map((l: any) => this.enrichLog(l));
                    this.logs = [...this.logs, ...incoming];
                    this.serverOffset = this.logs.length;
                    this.serverTotal = Number(response?.total ?? this.serverTotal);
                    this.serverHasMore = !!response?.has_more;
                    this.rebuildAvailableFilters();
                    this.applyFilters();
                    this.serverLoading = false;
                    this.isLoadingMore = false;
                },
                error: () => {
                    this.serverLoading = false;
                    this.isLoadingMore = false;
                    this.serverHasMore = false;
                },
            });
    }

    exportLogsAsJsonl(): void {
        if (!this.filteredLogs.length) {
            return;
        }
        const lines = this.filteredLogs
            .map((log) => {
                const { tags, statusLabel, ...raw } = log;
                try {
                    return JSON.stringify(raw);
                } catch {
                    return '';
                }
            })
            .filter(Boolean)
            .join('\n');
        const blob = new Blob([lines], { type: 'application/x-ndjson' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `debug_${this.currentSessionId || 'session'}.jsonl`;
        anchor.click();
        URL.revokeObjectURL(url);
    }

    private tryExtendVisibleWindow(): void {
        if (!this.hasMoreLogs) {
            return;
        }
        const container = this.debugLogContainer?.nativeElement;
        if (container) {
            const remaining = container.scrollHeight - (container.scrollTop + container.clientHeight);
            if (remaining <= this.SCROLL_THRESHOLD_PX) {
                this.extendVisibleWindow();
            }
            return;
        }
        const doc = document.documentElement;
        const remaining = doc.scrollHeight - (window.scrollY + window.innerHeight);
        if (remaining <= this.SCROLL_THRESHOLD_PX) {
            this.extendVisibleWindow();
        }
    }

    private ensureViewportFilled(): void {
        const container = this.debugLogContainer?.nativeElement;
        if (!container) {
            this.tryExtendVisibleWindow();
            return;
        }
        while (this.hasMoreLogs && container.scrollHeight - container.clientHeight <= this.SCROLL_THRESHOLD_PX) {
            const before = this.visibleCount;
            this.extendVisibleWindow();
            if (this.visibleCount === before) {
                break;
            }
        }
    }

    private extendVisibleWindow(): void {
        if (!this.hasMoreLogs) {
            return;
        }
        // Client window exhausted but the server has more rows — pull the
        // next page before extending the visible slice.
        if (this.visibleCount >= this.filteredLogs.length && this.serverHasMore) {
            this.loadNextServerPage();
            return;
        }
        this.isLoadingMore = true;
        this.visibleCount = Math.min(this.visibleCount + this.PAGE_SIZE, this.filteredLogs.length);
        this.rebuildVisibleLogs();
        this.isLoadingMore = false;
        setTimeout(() => this.ensureViewportFilled(), 0);
    }

    private rebuildAvailableFilters(): void {
        this.availableSources = Array.from(
            new Set<string>(([] as string[]).concat(...this.logs.map((l: any) => l.tags || [])))
        ).sort();

        this.availableStatuses = Array.from(
            new Set(this.logs.map((l) => l.statusLabel).filter(Boolean))
        ).sort();
    }

    private rebuildVisibleLogs(): void {
        this.visibleLogs = this.filteredLogs.slice(0, this.visibleCount);
        this.hasMoreLogs = this.visibleCount < this.filteredLogs.length || this.serverHasMore;
    }

    private enrichLog(log: any) {
        const tags = this.extractTags(log);
        const statusLabel = this.getStatusLabel(log);
        return { ...log, tags, statusLabel };
    }

    private extractTags(log: any): string[] {
        const fields: (string | undefined)[] = [
            log.msg,
            log.details?.msg,
            log.details?.error,
            log.details?.status,
            log.details?.context,
            log.event_type,
            log.meta?.source,
        ].filter((v): v is string => typeof v === 'string');

        const collected: string[] = [];
        for (const txt of fields) {
            const safeTxt = txt || '';
            let m: RegExpExecArray | null;
            while ((m = TAG_RE.exec(safeTxt)) !== null) {
                const tag = m[1].trim();
                if (tag) collected.push(tag);
            }
        }

        if (collected.length === 0) {
            if (typeof log.event_type === 'string' && log.event_type.trim()) {
                collected.push(log.event_type.trim());
            } else if (typeof log.meta?.source === 'string' && log.meta.source.trim()) {
                collected.push(log.meta.source.trim());
            }
        }

        return Array.from(new Set(collected));
    }

    private getStatusLabel(log: any): string {
        const raw =
            log.status ||
            log.details?.status ||
            log.meta?.severity ||
            (typeof log.event_type === 'string' && log.event_type.toLowerCase().includes('error') ? 'Error' : '');

        const s = String(raw || '').toLowerCase();
        if (!s) return 'Info';
        if (s.includes('error')) return 'Error';
        if (s.includes('success') || s === 'ok') return 'Success';
        if (s.includes('warn')) return 'Warning';
        if (s.includes('debug')) return 'Debug';
        if (s.includes('info')) return 'Info';
        return raw || 'Info';
    }

    hasDetails(log: any): boolean {
        if (!log.details) return false;
        if (typeof log.details === 'object' && Object.keys(log.details).length === 0) {
            return false;
        }
        if (JSON.stringify(log.details) === '{}') {
            return false;
        }
        return true;
    }

    formatDetails(details: any): string {
        return JSON.stringify(this.expandNestedJson(details), null, 2);
    }

    toggleDetails(index: number): void {
        if (this.expandedLogs.has(index)) this.expandedLogs.delete(index);
        else this.expandedLogs.add(index);
    }

    getLogClass(log: any): string {
        switch (log.statusLabel) {
            case 'Error':
                return 'error';
            case 'Success':
                return 'success';
            case 'Warning':
                return 'warning';
            case 'Debug':
                return 'debug';
            default:
                return 'audit';
        }
    }

    applyFilters(): void {
        let data = this.logs;

        if (this.activeSources.length > 0) {
            data = data.filter((log) => (log.tags || []).some((t: string) => this.activeSources.includes(t)));
        }

        if (this.activeStatuses.length > 0) {
            data = data.filter((log) => this.activeStatuses.includes(log.statusLabel));
        }

        this.filteredLogs = data;
        this.visibleCount = Math.min(Math.max(this.PAGE_SIZE, this.visibleCount), this.filteredLogs.length || this.PAGE_SIZE);
        this.rebuildVisibleLogs();
        setTimeout(() => this.ensureViewportFilled(), 0);
    }

    toggleSource(source: string): void {
        if (this.activeSources.includes(source)) {
            this.activeSources = this.activeSources.filter((s) => s !== source);
        } else {
            this.activeSources = [...this.activeSources, source];
        }
        this.applyFilters();
    }

    removeSource(event: MouseEvent, source: string): void {
        event.stopPropagation();
        this.activeSources = this.activeSources.filter((s) => s !== source);
        this.applyFilters();
    }

    toggleStatus(status: string): void {
        if (this.activeStatuses.includes(status)) {
            this.activeStatuses = this.activeStatuses.filter((s) => s !== status);
        } else {
            this.activeStatuses = [...this.activeStatuses, status];
        }
        this.applyFilters();
    }

    removeStatus(event: MouseEvent, status: string): void {
        event.stopPropagation();
        this.activeStatuses = this.activeStatuses.filter((s) => s !== status);
        this.applyFilters();
    }

    private expandNestedJson(value: any, depth = 0): any {
        if (depth > 6 || value === null || value === undefined) {
            return value;
        }
        if (typeof value === 'string') {
            return this.parseJsonString(value, depth);
        }
        if (Array.isArray(value)) {
            return value.map((item) => this.expandNestedJson(item, depth + 1));
        }
        if (typeof value === 'object') {
            const expanded: Record<string, any> = {};
            Object.entries(value).forEach(([key, item]) => {
                expanded[key] = this.expandNestedJson(item, depth + 1);
            });
            return expanded;
        }
        return value;
    }

    private parseJsonString(value: string, depth: number): any {
        if (!JSON_LIKE_RE.test(value)) {
            return value;
        }
        try {
            const parsed = JSON.parse(value);
            if (parsed && typeof parsed === 'object') {
                return this.expandNestedJson(parsed, depth + 1);
            }
        } catch {
            return value;
        }
        return value;
    }
}
