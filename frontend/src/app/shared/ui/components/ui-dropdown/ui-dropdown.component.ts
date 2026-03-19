import {
    Component,
    ElementRef,
    EventEmitter,
    HostListener,
    Input,
    Output,
} from '@angular/core';

@Component({
    selector: 'app-ui-dropdown',
    templateUrl: './ui-dropdown.component.html',
    styleUrls: ['./ui-dropdown.component.less'],
})
export class UiDropdownComponent {
    @Input() open = false;
    @Input() disabled = false;
    @Input() closeOnMenuClick = true;
    @Input() align: 'left' | 'right' = 'left';

    @Output() openChange = new EventEmitter<boolean>();

    constructor(private readonly elementRef: ElementRef<HTMLElement>) {}

    @HostListener('document:click', ['$event'])
    onDocumentClick(event: Event): void {
        if (!this.open) {
            return;
        }

        const target = event.target as Node | null;
        if (target && !this.elementRef.nativeElement.contains(target)) {
            this.updateOpen(false);
        }
    }

    toggle(event: Event): void {
        event.stopPropagation();
        if (this.disabled) {
            return;
        }
        this.updateOpen(!this.open);
    }

    onMenuClick(event: Event): void {
        event.stopPropagation();
        if (this.closeOnMenuClick) {
            this.updateOpen(false);
        }
    }

    updateOpen(value: boolean): void {
        this.open = value;
        this.openChange.emit(value);
    }
}
