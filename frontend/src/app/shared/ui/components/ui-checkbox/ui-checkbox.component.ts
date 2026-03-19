import { Component, EventEmitter, forwardRef, Input, Output } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

@Component({
    selector: 'app-ui-checkbox',
    templateUrl: './ui-checkbox.component.html',
    styleUrls: ['./ui-checkbox.component.less'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => UiCheckboxComponent),
            multi: true,
        },
    ],
})
export class UiCheckboxComponent implements ControlValueAccessor {
    @Input() id = '';
    @Input() disabled = false;
    @Input() readonly: boolean | string = false;
    @Input() label = '';

    @Output() checkedChange = new EventEmitter<boolean>();

    checked = false;

    private onTouched: () => void = () => undefined;
    private onChange: (value: boolean) => void = () => undefined;

    writeValue(value: any): void {
        this.checked = !!value;
    }

    registerOnChange(fn: any): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: any): void {
        this.onTouched = fn;
    }

    setDisabledState(disabled: boolean): void {
        this.disabled = disabled;
    }

    toggle(): void {
        if (this.isReadonly || this.disabled) {
            return;
        }
        const nextValue = !this.checked;
        this.checked = nextValue;
        this.onChange(nextValue);
        this.checkedChange.emit(nextValue);
    }

    markTouched(): void {
        this.onTouched();
    }

    get isReadonly(): boolean {
        return this.readonly !== false && this.readonly !== 'false';
    }
}
