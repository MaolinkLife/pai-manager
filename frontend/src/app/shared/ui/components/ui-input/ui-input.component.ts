import { Component, EventEmitter, forwardRef, Input, Output } from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

@Component({
    selector: 'app-ui-input',
    templateUrl: './ui-input.component.html',
    styleUrls: ['./ui-input.component.less'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => UiInputComponent),
            multi: true,
        },
    ],
})
export class UiInputComponent implements ControlValueAccessor {
    @Input() type: 'text' | 'number' | 'password' | 'email' = 'text';
    @Input() placeholder = '';
    @Input() disabled = false;
    @Input() readonly: boolean | string = false;
    @Input() min: number | string | null = null;
    @Input() max: number | string | null = null;
    @Input() step: number | string | null = null;

    @Output() valueChange = new EventEmitter<string | number | null>();

    value: string | number | null = '';

    private onTouched: () => void = () => undefined;
    private onChange: (value: any) => void = () => undefined;

    writeValue(value: any): void {
        this.value = value ?? '';
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

    onInputEvent(event: Event): void {
        const target = event.target as HTMLInputElement | null;
        const value = target ? target.value : '';
        const nextValue =
            this.type === 'number'
                ? value === ''
                    ? null
                    : Number(value)
                : value;
        this.value = nextValue;
        this.onChange(nextValue);
        this.valueChange.emit(nextValue);
    }

    increment(event: MouseEvent): void {
        event.preventDefault();
        event.stopPropagation();
        this.stepValue(1);
    }

    decrement(event: MouseEvent): void {
        event.preventDefault();
        event.stopPropagation();
        this.stepValue(-1);
    }

    markTouched(): void {
        this.onTouched();
    }

    private stepValue(direction: 1 | -1): void {
        if (this.disabled || this.isReadonly || this.type !== 'number') {
            return;
        }

        const step = this.toNumber(this.step, 1) ?? 1;
        const baseValue = typeof this.value === 'number' && !Number.isNaN(this.value)
            ? this.value
            : (this.toNumber(this.min, 0) ?? 0);
        const rawNext = baseValue + direction * step;
        const nextValue = this.clamp(rawNext);

        this.value = nextValue;
        this.onChange(nextValue);
        this.valueChange.emit(nextValue);
        this.onTouched();
    }

    private clamp(value: number): number {
        let next = value;
        const min = this.toNumber(this.min);
        const max = this.toNumber(this.max);

        if (typeof min === 'number') {
            next = Math.max(min, next);
        }
        if (typeof max === 'number') {
            next = Math.min(max, next);
        }
        return next;
    }

    get isReadonly(): boolean {
        return this.readonly !== false && this.readonly !== 'false';
    }

    private toNumber(value: number | string | null, fallback: number | null = null): number | null {
        if (value === null || value === undefined || value === '') {
            return fallback;
        }
        if (typeof value === 'number') {
            return Number.isNaN(value) ? fallback : value;
        }
        const parsed = Number(value);
        return Number.isNaN(parsed) ? fallback : parsed;
    }
}
