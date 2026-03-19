import {
    Component,
    EventEmitter,
    forwardRef,
    Input,
    Output,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

@Component({
    selector: 'app-ui-range',
    templateUrl: './ui-range.component.html',
    styleUrls: ['./ui-range.component.less'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => UiRangeComponent),
            multi: true,
        },
    ],
})
export class UiRangeComponent implements ControlValueAccessor {
    @Input() id = '';
    @Input() min: number | string = 0;
    @Input() max: number | string = 100;
    @Input() step: number | string = 1;
    @Input() disabled = false;
    @Input() minLabel = '';
    @Input() maxLabel = '';
    @Input() showEdgeLabels = false;
    @Input()
    set value(nextValue: number | string) {
        const parsed = Number(nextValue);
        if (!Number.isNaN(parsed)) {
            this._value = parsed;
        }
    }
    get value(): number {
        return this._value;
    }

    @Output() valueChange = new EventEmitter<number>();

    private _value = 0;

    private onTouched: () => void = () => undefined;
    private onChange: (value: number) => void = () => undefined;

    writeValue(value: any): void {
        const next = Number(value);
        this._value = Number.isNaN(next) ? this.toNumber(this.min, 0) : next;
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

    onInput(event: Event): void {
        const target = event.target as HTMLInputElement | null;
        const next = Number(target?.value);
        if (Number.isNaN(next)) {
            return;
        }

        const clamped = this.clamp(next);
        this._value = clamped;
        this.onChange(clamped);
        this.valueChange.emit(clamped);
    }

    markTouched(): void {
        this.onTouched();
    }

    private toNumber(value: number | string, fallback: number): number {
        if (typeof value === 'number') {
            return Number.isNaN(value) ? fallback : value;
        }

        const parsed = Number(value);
        return Number.isNaN(parsed) ? fallback : parsed;
    }

    get displayValue(): number {
        const min = this.toNumber(this.min, 0);
        const max = this.toNumber(this.max, 100);
        return Math.min(Math.max(this._value, min), max);
    }

    private clamp(value: number): number {
        const min = this.toNumber(this.min, 0);
        const max = this.toNumber(this.max, 100);
        return Math.min(Math.max(value, min), max);
    }
}
