import { Component, EventEmitter, forwardRef, Input, Output } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

export interface UiSelectOption<T = any> {
    label: string;
    value: T;
    disabled?: boolean;
}

@Component({
    selector: 'app-ui-select',
    templateUrl: './ui-select.component.html',
    styleUrls: ['./ui-select.component.less'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => UiSelectComponent),
            multi: true,
        },
    ],
})
export class UiSelectComponent implements ControlValueAccessor {
    @Input() placeholder = 'Select...';
    @Input() disabled = false;
    @Input() options: Array<UiSelectOption | string | number> = [];
    @Input() includePlaceholderOption = false;
    @Input() value: any = null;
    @Output() change = new EventEmitter<{ target: { value: any } }>();
    open = false;

    private onTouched: () => void = () => undefined;
    private onChange: (value: any) => void = () => undefined;

    get normalizedOptions(): UiSelectOption[] {
        return (this.options || []).map((option) => {
            if (typeof option === 'string' || typeof option === 'number') {
                return { label: String(option), value: option };
            }
            return option;
        });
    }

    writeValue(value: any): void {
        this.value = value;
    }

    get usesCustomDropdown(): boolean {
        return this.normalizedOptions.length > 0;
    }

    get selectedLabel(): string {
        const matched = this.normalizedOptions.find((option) => option.value === this.value);
        return matched ? matched.label : '';
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

    onNativeChange(event: Event): void {
        const target = event.target as HTMLSelectElement | null;
        const raw = target ? target.value : '';
        const matched = this.normalizedOptions.find(
            (option) => String(option.value) === raw
        );
        const nextValue = matched ? matched.value : raw;

        this.value = nextValue;
        this.onChange(nextValue);
        this.onTouched();
        this.change.emit({ target: { value: nextValue } });
    }

    onOptionSelect(value: any): void {
        this.value = value;
        this.onChange(value);
        this.onTouched();
        this.open = false;
        this.change.emit({ target: { value } });
    }

    markTouched(): void {
        this.onTouched();
    }

    trackByValue(_index: number, item: UiSelectOption): any {
        return item.value;
    }
}
