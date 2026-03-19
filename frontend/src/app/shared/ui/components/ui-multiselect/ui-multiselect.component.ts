import { Component, forwardRef, Input } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';
import { UiSelectOption } from '../ui-select/ui-select.component';

@Component({
    selector: 'app-ui-multiselect',
    templateUrl: './ui-multiselect.component.html',
    styleUrls: ['./ui-multiselect.component.less'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => UiMultiselectComponent),
            multi: true,
        },
    ],
})
export class UiMultiselectComponent implements ControlValueAccessor {
    @Input() placeholder = 'Select...';
    @Input() disabled = false;
    @Input() options: Array<UiSelectOption | string | number> = [];

    open = false;
    value: any[] = [];

    private onTouched: () => void = () => undefined;
    private onChange: (value: any[]) => void = () => undefined;

    get normalizedOptions(): UiSelectOption[] {
        return (this.options || []).map((option) => {
            if (typeof option === 'string' || typeof option === 'number') {
                return { label: String(option), value: option };
            }
            return option;
        });
    }

    get valueLabel(): string {
        if (!this.value.length) {
            return this.placeholder;
        }

        const selected = this.normalizedOptions
            .filter((option) => this.value.includes(option.value))
            .map((option) => option.label);

        return selected.join(', ');
    }

    writeValue(value: any): void {
        this.value = Array.isArray(value) ? value : [];
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

    isSelected(value: any): boolean {
        return this.value.includes(value);
    }

    toggleOption(value: any): void {
        if (this.disabled) {
            return;
        }

        if (this.isSelected(value)) {
            this.value = this.value.filter((item) => item !== value);
        } else {
            this.value = [...this.value, value];
        }

        this.onChange(this.value);
        this.onTouched();
    }

    trackByValue(_index: number, item: UiSelectOption): any {
        return item.value;
    }
}
