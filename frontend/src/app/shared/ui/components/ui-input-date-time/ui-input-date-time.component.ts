import {
    Component,
    ElementRef,
    EventEmitter,
    forwardRef,
    HostListener,
    Input,
    Output,
    ViewChild,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

interface CalendarCell {
    key: string;
    dayNumber: number;
    inMonth: boolean;
    isToday: boolean;
    isSelected: boolean;
    isDisabled: boolean;
    date: Date;
}

const MASK_PLACEHOLDER = 'дд.мм.гггг чч:мм';
const DIGITS_FULL = 12; // DDMMYYYYHHMM
const DEFAULT_PICK_HOUR = 9;

/**
 * Date-time input with an input mask (DD.MM.YYYY HH:MM) and a popup month
 * calendar. Value is a Date or null (incomplete/invalid input = null).
 * Typing is digits-only: separators are inserted automatically and segments
 * are auto-corrected on the fly (month <= 12, hours <= 23 and so on).
 */
@Component({
    selector: 'app-ui-input-date-time',
    templateUrl: './ui-input-date-time.component.html',
    styleUrls: ['./ui-input-date-time.component.less'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => UiInputDateTimeComponent),
            multi: true,
        },
    ],
    standalone: false
})
export class UiInputDateTimeComponent implements ControlValueAccessor {
    @Input() placeholder = MASK_PLACEHOLDER;
    @Input() disabled = false;
    @Input() min: Date | null = null;

    @Output() valueChange = new EventEmitter<Date | null>();

    @ViewChild('field') private fieldRef?: ElementRef<HTMLInputElement>;

    text = '';
    open = false;
    viewMonth = new Date();
    weeks: CalendarCell[][] = [];
    weekdayLabels: string[] = [];
    monthLabel = '';

    private value: Date | null = null;
    private onChange: (value: Date | null) => void = () => undefined;
    private onTouched: () => void = () => undefined;

    constructor(private readonly elementRef: ElementRef<HTMLElement>) {
        this.buildWeekdayLabels();
    }

    // ------------------------------------------------------------------ CVA

    writeValue(value: Date | string | null): void {
        const parsed = this.coerceDate(value);
        this.value = parsed;
        this.text = parsed ? this.format(parsed) : '';
        if (parsed) {
            this.viewMonth = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
        }
        this.rebuildCalendar();
    }

    registerOnChange(fn: (value: Date | null) => void): void {
        this.onChange = fn;
    }

    registerOnTouched(fn: () => void): void {
        this.onTouched = fn;
    }

    setDisabledState(disabled: boolean): void {
        this.disabled = disabled;
        if (disabled) {
            this.open = false;
        }
    }

    // ------------------------------------------------------------- text mask

    onInput(event: Event): void {
        const input = event.target as HTMLInputElement;
        const digits = input.value.replace(/\D/g, '').slice(0, DIGITS_FULL);
        this.text = this.applyMask(digits);
        input.value = this.text;
        this.commitFromText();
    }

    onBlur(): void {
        this.onTouched();
    }

    onFieldKeydown(event: KeyboardEvent): void {
        if (event.key === 'Escape' && this.open) {
            event.stopPropagation();
            this.open = false;
        }
    }

    /** Digits → "DD.MM.YYYY HH:MM" with per-segment auto-correction. */
    private applyMask(raw: string): string {
        let digits = '';
        for (const char of raw) {
            digits += this.correctedDigit(digits, char);
        }

        let result = '';
        for (let i = 0; i < digits.length; i++) {
            if (i === 2 || i === 4) {
                result += '.';
            } else if (i === 8) {
                result += ' ';
            } else if (i === 10) {
                result += ':';
            }
            result += digits[i];
        }
        return result;
    }

    /** Per-position correction so impossible segments cannot be typed. */
    private correctedDigit(before: string, char: string): string {
        const position = before.length;
        const digit = Number(char);

        switch (position) {
            case 0: // day, first digit: 4-9 → 04-09
                return digit > 3 ? `0${char}` : char;
            case 1: { // day, second digit: clamp 00 → 01, 32-39 → 31
                const day = Number(before[0] + char);
                if (day === 0) {
                    return '1';
                }
                return day > 31 ? '1' : char;
            }
            case 2: // month, first digit: 2-9 → 02-09
                return digit > 1 ? `0${char}` : char;
            case 3: { // month, second digit: 00 → 01, 13+ → 12
                const month = Number(before[2] + char);
                if (month === 0) {
                    return '1';
                }
                return month > 12 ? '2' : char;
            }
            case 8: // hours, first digit: 3-9 → 03-09
                return digit > 2 ? `0${char}` : char;
            case 9: { // hours, second digit: 24-29 → 23
                const hours = Number(before[8] + char);
                return hours > 23 ? '3' : char;
            }
            case 10: // minutes, first digit: 6-9 → 06-09
                return digit > 5 ? `0${char}` : char;
            default:
                return char;
        }
    }

    private commitFromText(): void {
        const digits = this.text.replace(/\D/g, '');
        if (digits.length < DIGITS_FULL) {
            this.setValue(null);
            return;
        }

        const day = Number(digits.slice(0, 2));
        const month = Number(digits.slice(2, 4));
        const year = Number(digits.slice(4, 8));
        const hours = Number(digits.slice(8, 10));
        const minutes = Number(digits.slice(10, 12));

        const candidate = new Date(year, month - 1, day, hours, minutes);
        const valid =
            candidate.getFullYear() === year &&
            candidate.getMonth() === month - 1 &&
            candidate.getDate() === day;

        if (!valid) {
            this.setValue(null);
            return;
        }

        this.setValue(candidate);
        this.viewMonth = new Date(year, month - 1, 1);
        this.rebuildCalendar();
    }

    get invalid(): boolean {
        const digits = this.text.replace(/\D/g, '');
        return digits.length > 0 && this.value === null;
    }

    // -------------------------------------------------------------- calendar

    toggleCalendar(): void {
        if (this.disabled) {
            return;
        }
        this.open = !this.open;
        if (this.open) {
            this.viewMonth = this.value
                ? new Date(this.value.getFullYear(), this.value.getMonth(), 1)
                : new Date();
            this.rebuildCalendar();
        }
    }

    previousMonth(event: MouseEvent): void {
        event.stopPropagation();
        this.viewMonth = new Date(this.viewMonth.getFullYear(), this.viewMonth.getMonth() - 1, 1);
        this.rebuildCalendar();
    }

    nextMonth(event: MouseEvent): void {
        event.stopPropagation();
        this.viewMonth = new Date(this.viewMonth.getFullYear(), this.viewMonth.getMonth() + 1, 1);
        this.rebuildCalendar();
    }

    goToCurrentMonth(event: MouseEvent): void {
        event.stopPropagation();
        this.viewMonth = new Date();
        this.rebuildCalendar();
    }

    pickDay(cell: CalendarCell, event: MouseEvent): void {
        event.stopPropagation();
        if (cell.isDisabled) {
            return;
        }
        const hours = this.value ? this.value.getHours() : DEFAULT_PICK_HOUR;
        const minutes = this.value ? this.value.getMinutes() : 0;
        const picked = new Date(
            cell.date.getFullYear(),
            cell.date.getMonth(),
            cell.date.getDate(),
            hours,
            minutes,
        );
        this.setValue(picked);
        this.text = this.format(picked);
        this.open = false;
        this.onTouched();
        this.fieldRef?.nativeElement.focus();
    }

    @HostListener('document:click', ['$event.target'])
    onDocumentClick(target: EventTarget | null): void {
        const inside = target instanceof Node && this.elementRef.nativeElement.contains(target);
        if (this.open && !inside) {
            this.open = false;
            this.onTouched();
        }
    }

    @HostListener('document:keydown.escape')
    onDocumentEscape(): void {
        this.open = false;
    }

    trackByCell(_index: number, cell: CalendarCell): string {
        return cell.key;
    }

    private rebuildCalendar(): void {
        const monthStart = new Date(this.viewMonth.getFullYear(), this.viewMonth.getMonth(), 1);
        const startOffset = (monthStart.getDay() + 6) % 7;
        const cursor = new Date(monthStart);
        cursor.setDate(monthStart.getDate() - startOffset);

        const todayKey = this.dayKey(new Date());
        const selectedKey = this.value ? this.dayKey(this.value) : null;
        const minKey = this.min ? this.dayKey(this.min) : null;

        const weeks: CalendarCell[][] = [];
        for (let week = 0; week < 6; week++) {
            const row: CalendarCell[] = [];
            for (let day = 0; day < 7; day++) {
                const key = this.dayKey(cursor);
                row.push({
                    key,
                    dayNumber: cursor.getDate(),
                    inMonth: cursor.getMonth() === monthStart.getMonth(),
                    isToday: key === todayKey,
                    isSelected: key === selectedKey,
                    isDisabled: minKey !== null && key < minKey,
                    date: new Date(cursor),
                });
                cursor.setDate(cursor.getDate() + 1);
            }
            weeks.push(row);
        }
        this.weeks = weeks;
        this.monthLabel = new Intl.DateTimeFormat(this.locale(), {
            month: 'long',
            year: 'numeric',
        }).format(monthStart);
    }

    private buildWeekdayLabels(): void {
        // 2024-01-01 is a Monday; the grid is Monday-based.
        const formatter = new Intl.DateTimeFormat(this.locale(), { weekday: 'short' });
        this.weekdayLabels = Array.from({ length: 7 }, (_value, index) =>
            formatter.format(new Date(2024, 0, 1 + index)),
        );
    }

    // -------------------------------------------------------------- helpers

    private setValue(value: Date | null): void {
        const changed =
            (this.value === null) !== (value === null) ||
            (this.value !== null && value !== null && this.value.getTime() !== value.getTime());
        this.value = value;
        if (changed) {
            this.onChange(value);
            this.valueChange.emit(value);
            this.rebuildCalendar();
        }
    }

    private format(date: Date): string {
        const pad = (value: number) => String(value).padStart(2, '0');
        return `${pad(date.getDate())}.${pad(date.getMonth() + 1)}.${date.getFullYear()} ` +
            `${pad(date.getHours())}:${pad(date.getMinutes())}`;
    }

    private coerceDate(value: Date | string | null): Date | null {
        if (!value) {
            return null;
        }
        const parsed = value instanceof Date ? value : new Date(value);
        return Number.isNaN(parsed.getTime()) ? null : parsed;
    }

    private dayKey(date: Date): string {
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${date.getFullYear()}-${month}-${day}`;
    }

    private locale(): string {
        return typeof navigator !== 'undefined' ? navigator.language || 'ru-RU' : 'ru-RU';
    }
}
