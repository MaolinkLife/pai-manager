import { TestBed } from '@angular/core/testing';
import { ChatComponent } from '../chat.component';
import { ChatSessionStateService } from './chat-session-state.service';

/** Opening the chat tab creates a new page; leaving it destroys the page. */
function openChatPage(session: ChatSessionStateService): ChatComponent {
    const unused = {} as any;
    return TestBed.runInInjectionContext(() => new ChatComponent(
        unused, unused, unused, unused, unused, unused, unused,
        unused, unused, unused, unused, session,
    ));
}

function leaveChatPage(page: ChatComponent): void {
    page.ngOnDestroy();
}

describe('ChatSessionStateService', () => {
    let session: ChatSessionStateService;

    beforeEach(() => {
        session = new ChatSessionStateService();
    });

    it('shows a running generation after the user comes back to the chat', () => {
        const first = openChatPage(session);
        first.loading = true;
        first.activeGenerationRunId = 'run-1';
        first.refreshHistoryAfterRunId = 'run-1';
        leaveChatPage(first);

        const second = openChatPage(session);
        expect(second.loading).toBeTrue();
        expect(second.activeGenerationRunId).toBe('run-1');
        expect(second.refreshHistoryAfterRunId).toBe('run-1');

        second.loading = false;
        second.activeGenerationRunId = null;
        leaveChatPage(second);

        const third = openChatPage(session);
        expect(third.loading).toBeFalse();
        expect(third.activeGenerationRunId).toBeNull();
    });

    it('shows an image being drawn, a recording and attachments being processed after coming back', () => {
        const first = openChatPage(session);
        first.illustratingMessageId = 'm1';
        first.recording = true;
        first.isProcessingAttachments = true;
        leaveChatPage(first);

        const second = openChatPage(session);
        expect(second.illustratingMessageId).toBe('m1');
        expect(second.recording).toBeTrue();
        expect(second.isProcessingAttachments).toBeTrue();
    });

    it('keeps the unsent draft text and attachments when the chat is left', () => {
        const first = openChatPage(session);
        first.chatInput.setValue('недописанное сообщение');
        first.attachments = [{ id: 'a1', name: 'photo.png' } as any];
        first.contextAttachments = [{ id: 'c1', type: 'note', title: 'заметка' }];
        leaveChatPage(first);

        const second = openChatPage(session);
        expect(second.chatInput.value).toBe('недописанное сообщение');
        expect(second.attachments.map((item) => item.id)).toEqual(['a1']);
        expect(second.contextAttachments.map((item) => item.id)).toEqual(['c1']);
    });
});
