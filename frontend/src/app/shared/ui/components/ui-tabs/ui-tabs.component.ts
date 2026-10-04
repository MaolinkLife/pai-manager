import { Component, EventEmitter, HostListener, Input, Output } from '@angular/core';

/** What the tab list needs from a single tab. */
export interface UiTabRef {
    key: string;
    disabled: boolean;
    focus(): void;
}

/**
 * Tab list. Tabs are projected as `<app-ui-tab key="...">label</app-ui-tab>`,
 * so labels and their translation stay with the page. The list tracks only
 * which key is active; the page renders the panels itself.
 *
 * - `activeKey` is two-way bindable: `[(activeKey)]="tab"`. The page owns it:
 *   the list never picks a tab on its own.
 * - Clicking a disabled or already active tab does nothing and emits nothing.
 * - Arrow Left/Right move to the previous/next enabled tab (wrapping around),
 *   Home/End to the first/last one. Moving activates the tab and focuses it.
 */
@Component({
    selector: 'app-ui-tabs',
    templateUrl: './ui-tabs.component.html',
    styleUrls: ['./ui-tabs.component.less'],
    standalone: false
})
export class UiTabsComponent {
    @Input() activeKey: string | null = null;

    @Output() activeKeyChange = new EventEmitter<string>();

    private readonly tabs: UiTabRef[] = [];

    register(tab: UiTabRef): void {
        this.tabs.push(tab);
    }

    unregister(tab: UiTabRef): void {
        const index = this.tabs.indexOf(tab);
        if (index >= 0) {
            this.tabs.splice(index, 1);
        }
    }

    isActive(key: string): boolean {
        return this.activeKey === key;
    }

    select(key: string): void {
        const tab = this.tabs.find((item) => item.key === key);
        if (!tab || tab.disabled || key === this.activeKey) {
            return;
        }
        this.activeKey = key;
        this.activeKeyChange.emit(key);
    }

    @HostListener('keydown', ['$event'])
    onKeydown(event: KeyboardEvent): void {
        const enabled = this.tabs.filter((item) => !item.disabled);
        if (enabled.length === 0) {
            return;
        }
        const current = enabled.findIndex((item) => item.key === this.activeKey);
        const last = enabled.length - 1;
        let next: number;
        switch (event.key) {
            case 'ArrowRight':
                next = current < 0 || current === last ? 0 : current + 1;
                break;
            case 'ArrowLeft':
                next = current <= 0 ? last : current - 1;
                break;
            case 'Home':
                next = 0;
                break;
            case 'End':
                next = last;
                break;
            default:
                return;
        }
        event.preventDefault();
        const target = enabled[next];
        this.select(target.key);
        target.focus();
    }
}
