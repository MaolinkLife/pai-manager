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
    newDueAt = '';

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
        this.load();
    }

    load(): void {
        this.loading = true;
        this.error = '';
        this.statusSelectOptions = this.statusKeys.map((item) => ({
            label: this.t(item.labelKey),
            value: item.value,
        }));
        this.reminderService.list$({ status: this.statusFilter || undefined, limit: 200 }).subscribe({
            next: (response) => {
                const rows = Array.isArray(response?.items) ? response.items : [];
                this.items = rows.map((row) => this.mapRow(row));
                this.total = Number(response?.total ?? rows.length);
                this.loading = false;
            },
            error: () => {
                this.items = [];
                this.loading = false;
                this.error = 'Failed to load reminders';
            },
        });
    }

    onStatusFilterChanged(value: string): void {
        this.statusFilter = value || '';
        this.load();
    }

    create(): void {
        this.formError = '';
        const text = this.newText.trim();
        const dueLocal = this.newDueAt.trim();
        if (!text || !dueLocal) {
            this.formError = this.t('tasks.invalidForm');
            return;
        }
        const due = new Date(dueLocal);
        if (Number.isNaN(due.getTime()) || due.getTime() <= Date.now()) {
            this.formError = this.t('tasks.invalidForm');
            return;
        }
        this.saving = true;
        this.reminderService.create$({ text, due_at: due.toISOString() }).subscribe({
            next: () => {
                this.saving = false;
                this.newText = '';
                this.newDueAt = '';
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

    statusLabel(status: ReminderDto['status']): string {
        return this.t(`tasks.${status}`);
    }

    private t(key: string): string {
        return this.localizationService.t(key);
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
        };
    }

    private formatMoment(value: string | null): string {
        if (!value) {
            return '';
        }
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return value;
        }
        const locale = this.localizationService.currentLang() || 'ru-RU';
        return new Intl.DateTimeFormat(locale, {
            day: '2-digit',
            month: '2-digit',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
        }).format(parsed);
    }
}
