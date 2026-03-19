import { Component, EventEmitter, Input, Output } from '@angular/core';

@Component({
    selector: 'app-ui-button',
    templateUrl: './ui-button.component.html',
    styleUrls: ['./ui-button.component.less'],
})
export class UiButtonComponent {
    @Input() type: 'button' | 'submit' | 'reset' = 'button';
    @Input() variant: 'primary' | 'secondary' | 'ghost' = 'primary';
    @Input() size: 'sm' | 'md' | 'lg' = 'md';
    @Input() disabled = false;
    @Input() loading = false;
    @Input() iconName: string | null = null;
    @Input() iconSize = 16;
    @Input() fullWidth = false;

    @Output() pressed = new EventEmitter<MouseEvent>();

    onClick(event: MouseEvent): void {
        if (this.disabled || this.loading) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        this.pressed.emit(event);
    }
}
