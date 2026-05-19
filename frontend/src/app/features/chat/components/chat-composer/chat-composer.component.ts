import {
    AfterViewInit,
    Component,
    ElementRef,
    EventEmitter,
    Input,
    Output,
    ViewChild,
} from '@angular/core';
import { UntypedFormControl } from '@angular/forms';
import { MessageMedia } from '../../../../core/models/message.model';

export interface ComposerContextAttachment {
    id: string;
    type: 'webpage' | 'note';
    title: string;
    subtitle?: string;
    url?: string;
    processing_mode?: 'link' | 'extract';
    status?: 'ready' | 'loading' | 'error';
}

@Component({
    selector: 'app-chat-composer',
    templateUrl: './chat-composer.component.html',
    styleUrls: ['./chat-composer.component.less'],
})
export class ChatComposerComponent implements AfterViewInit {
    @Input() chatInput!: UntypedFormControl;
    @Input() attachments: MessageMedia[] = [];
    @Input() isProcessingAttachments = false;
    @Input() activeDropdown: string | null = null;
    @Input() recording = false;
    @Input() voiceModeEnabled = false;
    @Input() voiceModeLoading = false;
    @Input() loading = false;
    @Input() activeGenerationRunId: string | null = null;
    @Input() imageGenerationEnabled = false;
    @Input() codeInterpreterEnabled = false;
    @Input() contextAttachments: ComposerContextAttachment[] = [];
    @Input() showEmojiPicker = false;
    @Input() emojiPickerMode: 'dropdown' | 'side-panel' = 'side-panel';
    @Input() emojiDropdownPosition: { x: number; y: number } = { x: 0, y: 0 };
    @Input() emojiPickerSide: 'left' | 'right' | 'top' | 'bottom' = 'right';

    @Output() submitMessage = new EventEmitter<void>();
    @Output() filesSelected = new EventEmitter<Event>();
    @Output() removeAttachment = new EventEmitter<string>();
    @Output() toggleAttach = new EventEmitter<Event>();
    @Output() toggleTools = new EventEmitter<Event>();
    @Output() toggleImageGeneration = new EventEmitter<void>();
    @Output() toggleCodeInterpreter = new EventEmitter<void>();
    @Output() openFile = new EventEmitter<MouseEvent>();
    @Output() openLibrary = new EventEmitter<MouseEvent>();
    @Output() captureScreen = new EventEmitter<MouseEvent>();
    @Output() attachWebpage = new EventEmitter<MouseEvent>();
    @Output() attachNotes = new EventEmitter<MouseEvent>();
    @Output() removeContextAttachment = new EventEmitter<string>();
    @Output() toggleEmoji = new EventEmitter<Event>();
    @Output() emojiSelect = new EventEmitter<string>();
    @Output() emojiClose = new EventEmitter<void>();
    @Output() toggleRecord = new EventEmitter<void>();
    @Output() toggleVoice = new EventEmitter<void>();
    @Output() stopGeneration = new EventEmitter<void>();
    @Output() expandComposer = new EventEmitter<Event>();

    @ViewChild('fileInput') private fileInputRef?: ElementRef<HTMLInputElement>;
    @ViewChild('chatTextarea') private chatTextareaRef?: ElementRef<HTMLTextAreaElement>;

    isComposerScrollable = false;

    ngAfterViewInit(): void {
        requestAnimationFrame(() => this.resizeTextarea());
    }

    openFilePicker(): void {
        this.fileInputRef?.nativeElement.click();
    }

    clearFileInput(): void {
        if (this.fileInputRef?.nativeElement) {
            this.fileInputRef.nativeElement.value = '';
        }
    }

    focusInput(): void {
        this.chatTextareaRef?.nativeElement?.focus();
    }

    resetTextareaHeight(): void {
        const textarea = this.chatTextareaRef?.nativeElement;
        if (!textarea) {
            return;
        }
        textarea.style.height = '48px';
        textarea.style.overflowY = 'hidden';
        this.isComposerScrollable = false;
    }

    resizeTextarea(): void {
        const textarea = this.chatTextareaRef?.nativeElement;
        if (!textarea) {
            return;
        }
        const minHeight = 48;
        const maxHeight = 132;
        textarea.style.height = '0px';
        const nextHeight = Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight);
        textarea.style.height = `${nextHeight}px`;
        this.isComposerScrollable = textarea.scrollHeight > maxHeight + 1;
        textarea.style.overflowY = this.isComposerScrollable ? 'auto' : 'hidden';
    }

    onSubmit(event: Event): void {
        event.preventDefault();
        this.submitMessage.emit();
    }

    onKeyDown(event: KeyboardEvent): void {
        if (event.key === 'Enter' && event.shiftKey) {
            return;
        }
        if (event.key === 'Enter') {
            event.preventDefault();
            this.submitMessage.emit();
        }
    }

    onFilesSelected(event: Event): void {
        this.filesSelected.emit(event);
    }

    trackByAttachment(_index: number, attachment: MessageMedia): string {
        return attachment.id;
    }

    trackByContextAttachment(_index: number, attachment: ComposerContextAttachment): string {
        return attachment.id;
    }
}
