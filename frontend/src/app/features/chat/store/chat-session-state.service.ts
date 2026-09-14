import { Injectable } from '@angular/core';
import { UntypedFormControl } from '@angular/forms';
import { MessageMedia } from '../../../core/models/message.model';
import type { ComposerContextAttachment } from '../components/chat-composer/chat-composer.component';

/**
 * What the chat is doing right now and what the user has not sent yet.
 *
 * Leaving the chat for another tab destroys the chat page. The work in
 * progress and the draft must not go with it: coming back, the user sees that
 * a generation is still running and finds the unsent text and files in place.
 */
@Injectable({ providedIn: 'root' })
export class ChatSessionStateService {
    generationActive = false;
    activeGenerationRunId: string | null = null;
    refreshHistoryAfterRunId: string | null = null;
    illustratingMessageId: string | null = null;
    recording = false;
    processingAttachments = false;

    /** The composer binds this control, so the draft text outlives the page. */
    readonly draft = new UntypedFormControl('');
    attachments: MessageMedia[] = [];
    contextAttachments: ComposerContextAttachment[] = [];
}
