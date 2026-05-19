import { AfterViewInit, Component, ElementRef, HostListener, OnInit, ViewChild } from '@angular/core';
import { LoggerService } from '../../core/services/logger.service';

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

    constructor(private loggerService: LoggerService) {}

    ngOnInit(): void {
        this.loadAllLogs();
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

    private loadAllLogs(): void {
        this.isInitialLoading = true;
        this.loggerService.getAllDebugLogs$(this.currentSessionId || undefined).subscribe({
            next: (response) => {
                this.logs = (response?.logs || []).map((l: any) => this.enrichLog(l));
                this.currentSessionId = String(response?.session_id || this.currentSessionId || '');
                this.rebuildAvailableFilters();
                this.applyFilters();
            },
            error: () => {
                this.logs = [];
                this.filteredLogs = [];
                this.visibleLogs = [];
                this.hasMoreLogs = false;
            },
            complete: () => {
                this.isInitialLoading = false;
                setTimeout(() => this.ensureViewportFilled(), 0);
            },
        });
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
        this.hasMoreLogs = this.visibleCount < this.filteredLogs.length;
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
