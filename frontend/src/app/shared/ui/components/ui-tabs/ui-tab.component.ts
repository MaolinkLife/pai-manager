import { Component, ElementRef, Input, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { UiTabRef, UiTabsComponent } from './ui-tabs.component';

/**
 * One tab inside `app-ui-tabs`; the projected content is its label.
 * Only the active tab is reachable with Tab, the rest with the arrow keys.
 * Used outside of `app-ui-tabs` it fails at creation: there is no list to join.
 */
@Component({
    selector: 'app-ui-tab',
    templateUrl: './ui-tab.component.html',
    styleUrls: ['./ui-tab.component.less'],
    standalone: false
})
export class UiTabComponent implements UiTabRef, OnInit, OnDestroy {
    @Input() key = '';
    @Input() disabled = false;

    @ViewChild('button', { static: true }) private buttonRef?: ElementRef<HTMLButtonElement>;

    constructor(private readonly tabs: UiTabsComponent) {}

    get active(): boolean {
        return this.tabs.isActive(this.key);
    }

    ngOnInit(): void {
        this.tabs.register(this);
    }

    ngOnDestroy(): void {
        this.tabs.unregister(this);
    }

    select(): void {
        this.tabs.select(this.key);
    }

    focus(): void {
        this.buttonRef?.nativeElement.focus();
    }
}
