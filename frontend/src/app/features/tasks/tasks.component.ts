import { Component, OnInit } from '@angular/core';
import { UiFeatureFlagsService } from '../../core/services/ui-feature-flags.service';
import { ReminderDto, ReminderService } from '../../core/services/reminder.service';
import { LocalizationService } from '../../shared/pipes/translation/localization.service';

interface ReminderView {
    id: string;
    text: string;
    status: ReminderDto['status'];
    dueLabel: string;
    createdLabel: string;
    sourceKey: string;
    canCancel: boolean;
    dueDate: Date | null;
}

interface CalendarDay {
    key: string;
    dayNumber: number;
    inMonth: boolean;
    isToday: boolean;
    items: ReminderView[];
}

@Component({
    selector: 'app-tasks',
    templateUrl: './tasks.component.html',
    styleUrls: ['./tasks.component.less'],
})
export class TasksComponent implements OnInit {
    readonly featureEnabled: boolean;

    loading = false;
    saving = false;
    error = '';
    formError = '';

    items: ReminderView[] = [];
    total = 0;

    statusFilter = '';
    newText = '';
    newDueAt: Date | null = null;
    readonly minDueDate = new Date();

    viewMode: 'list' | 'calendar' = 'list';
    calendarMonth = new Date();
    // Derived collections are fields rebuilt on data changes (never getters —
    // see CLAUDE.md gotcha #26 about getters + impure pipes in templates).
    calendarWeeks: CalendarDay[][] = [];
    weekdayLabels: string[] = [];
    monthLabel = '';
    selectedDayKey: string | null = null;
    selectedDayItems: ReminderView[] = [];

    private readonly statusKeys = [
        { value: '', labelKey: 'tasks.all' },
        { value: 'pending', labelKey: 'tasks.pending' },
        { value: 'fired', labelKey: 'tasks.fired' },
        { value: 'cancelled', labelKey: 'tasks.cancelled' },
        { value: 'failed', labelKey: 'tasks.failed' },
    ];
    statusSelectOptions: Array<{ label: string; value: string }> = [];

    constructor(
        uiFeatureFlags: UiFeatureFlagsService,
        private reminderService: ReminderService,
        private localizationService: LocalizationService,
    ) {
        this.featureEnabled = uiFeatureFlags.isEnabled('tasks');
    }

    ngOnInit(): void {
        if (!this.featureEnabled) {
            return;
        }
        this.localizationService.init();
        this.buildWeekdayLabels();
        this.load();
    }

    load(): void {
        this.loading = true;
        this.error = '';
        this.statusSelectOptions = this.statusKeys.map((item) => ({
            label: this.t(item.labelKey),
            value: item.value,
        }));
        this.reminderService.list$({ status: this.statusFilter || undefined, limit: 500 }).subscribe({
            next: (response) => {
                const rows = Array.isArray(response?.items) ? response.items : [];
                this.items = rows.map((row) => this.mapRow(row));
                this.total = Number(response?.total ?? rows.length);
                this.loading = false;
                this.rebuildCalendar();
            },
            error: () => {
                this.items = [];
                this.loading = false;
                this.error = 'Failed to load reminders';
                this.rebuildCalendar();
            },
        });
    }

    onStatusFilterChanged(value: string): void {
        this.statusFilter = value || '';
        this.load();
    }

    setViewMode(mode: 'list' | 'calendar'): void {
        this.viewMode = mode;
        if (mode === 'calendar') {
            this.rebuildCalendar();
        }
    }

    previousMonth(): void {
        this.calendarMonth = new Date(this.calendarMonth.getFullYear(), this.calendarMonth.getMonth() - 1, 1);
        this.rebuildCalendar();
    }

    nextMonth(): void {
        this.calendarMonth = new Date(this.calendarMonth.getFullYear(), this.calendarMonth.getMonth() + 1, 1);
        this.rebuildCalendar();
    }

    goToCurrentMonth(): void {
        this.calendarMonth = new Date();
        this.rebuildCalendar();
    }

    selectDay(day: CalendarDay): void {
        this.selectedDayKey = day.key;
        this.selectedDayItems = day.items;
        // Prefill the create form with the picked date (next morning slot).
        const prefill = new Date(`${day.key}T09:00`);
        if (prefill.getTime() > Date.now()) {
            this.newDueAt = prefill;
        }
    }

    create(): void {
        this.formError = '';
        const text = this.newText.trim();
        const due = this.newDueAt;
        if (!text || !due || due.getTime() <= Date.now()) {
            this.formError = this.t('tasks.invalidForm');
            return;
        }
        this.saving = true;
        this.reminderService.create$({ text, due_at: due.toISOString() }).subscribe({
            next: () => {
                this.saving = false;
                this.newText = '';
                this.newDueAt = null;
                this.load();
            },
            error: () => {
                this.saving = false;
                this.formError = this.t('tasks.invalidForm');
            },
        });
    }

    cancelReminder(id: string): void {
        this.reminderService.cancel$(id).subscribe({
            next: () => this.load(),
            error: () => this.load(),
        });
    }

    trackById(_index: number, item: ReminderView): string {
        return item.id;
    }

    trackByWeek(index: number): number {
        return index;
    }

    trackByDay(_index: number, day: CalendarDay): string {
        return day.key;
    }

    statusLabel(status: ReminderDto['status']): string {
        return this.t(`tasks.${status}`);
    }

    private t(key: string): string {
        return this.localizationService.t(key);
    }

    private locale(): string {
        return this.localizationService.currentLang() || 'ru-RU';
    }

    private dayKey(date: Date): string {
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${date.getFullYear()}-${month}-${day}`;
    }

    private buildWeekdayLabels(): void {
        // 2024-01-01 is a Monday; the grid is Monday-based.
        const formatter = new Intl.DateTimeFormat(this.locale(), { weekday: 'short' });
        this.weekdayLabels = Array.from({ length: 7 }, (_value, index) =>
            formatter.format(new Date(2024, 0, 1 + index))
        );
    }

    private rebuildCalendar(): void {
        const monthStart = new Date(this.calendarMonth.getFullYear(), this.calendarMonth.getMonth(), 1);
        const startOffset = (monthStart.getDay() + 6) % 7;
        const cursor = new Date(monthStart);
        cursor.setDate(monthStart.getDate() - startOffset);

        const byDay = new Map<string, ReminderView[]>();
        for (const item of this.items) {
            if (!item.dueDate) {
                continue;
            }
            const key = this.dayKey(item.dueDate);
            const bucket = byDay.get(key);
            if (bucket) {
                bucket.push(item);
            } else {
                byDay.set(key, [item]);
            }
        }

        const todayKey = this.dayKey(new Date());
        const weeks: CalendarDay[][] = [];
        for (let week = 0; week < 6; week++) {
            const row: CalendarDay[] = [];
            for (let day = 0; day < 7; day++) {
                const key = this.dayKey(cursor);
                row.push({
                    key,
                    dayNumber: cursor.getDate(),
                    inMonth: cursor.getMonth() === monthStart.getMonth(),
                    isToday: key === todayKey,
                    items: byDay.get(key) || [],
                });
                cursor.setDate(cursor.getDate() + 1);
            }
            weeks.push(row);
        }
        this.calendarWeeks = weeks;
        this.monthLabel = new Intl.DateTimeFormat(this.locale(), {
            month: 'long',
            year: 'numeric',
        }).format(monthStart);

        if (this.selectedDayKey) {
            this.selectedDayItems = byDay.get(this.selectedDayKey) || [];
        }
    }

    private mapRow(row: ReminderDto): ReminderView {
        return {
            id: row.id,
            text: row.text,
            status: row.status,
            dueLabel: this.formatMoment(row.due_at),
            createdLabel: this.formatMoment(row.created_at),
            sourceKey: row.source === 'api' ? 'tasks.sourceApi' : 'tasks.sourceChat',
            canCancel: row.status === 'pending',
            dueDate: this.parseMoment(row.due_at),
        };
    }

    private parseMoment(value: string | null): Date | null {
        if (!value) {
            return null;
        }
        const parsed = new Date(value);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    private formatMoment(value: string | null): string {
        const parsed = this.parseMoment(value);
        if (!parsed) {
            return value || '';
        }
        return new Intl.DateTimeFormat(this.locale(), {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
        }).format(parsed);
    }
}
