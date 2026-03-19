import {
    AfterViewInit,
    Component,
    ElementRef,
    EventEmitter,
    forwardRef,
    Input,
    Output,
    ViewChild,
} from '@angular/core';
import { ControlValueAccessor, NG_VALUE_ACCESSOR } from '@angular/forms';

@Component({
    selector: 'app-ui-textarea',
    templateUrl: './ui-textarea.component.html',
    styleUrls: ['./ui-textarea.component.less'],
    providers: [
        {
            provide: NG_VALUE_ACCESSOR,
            useExisting: forwardRef(() => UiTextareaComponent),
            multi: true,
        },
    ],
})
export class UiTextareaComponent implements ControlValueAccessor, AfterViewInit {
    @Input() id = '';
    @Input() placeholder = '';
    @Input() rows = 3;
    @Input() disabled = false;
    @Input() readonly: boolean | string = false;
    @Input() maxLength: number | null = null;
    @Input() autoResize = true;
    @Input() showCounter = false;

    @Output() valueChange = new EventEmitter<string>();

    @ViewChild('textareaElement') private textareaElement?: ElementRef<HTMLTextAreaElement>;

    value = '';

    private onTouched: () => void = () => undefined;
    private onChange: (value: string) => void = () => undefined;

    ngAfterViewInit(): void {
        this.adjustHeight();
    }

    writeValue(value: any): void {
        this.value = String(value ?? '');
        this.adjustHeight();
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
        const target = event.target as HTMLTextAreaElement | null;
        const nextValue = String(target?.value ?? '');
        this.value = nextValue;
        this.onChange(nextValue);
        this.valueChange.emit(nextValue);
        this.adjustHeight();
    }

    markTouched(): void {
        this.onTouched();
    }

    get isReadonly(): boolean {
        return this.readonly !== false && this.readonly !== 'false';
    }

    get currentLength(): number {
        return this.value.length;
    }

    private adjustHeight(): void {
        if (!this.autoResize || !this.textareaElement) {
            return;
        }

        const nativeElement = this.textareaElement.nativeElement;
        nativeElement.style.height = 'auto';
        nativeElement.style.height = `${nativeElement.scrollHeight}px`;
    }
}
