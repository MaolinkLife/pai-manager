import { isNearScrollBottom } from './chat-scroll.util';

describe('isNearScrollBottom', () => {
    it('treats the chat as sticky when the viewport is at the bottom', () => {
        expect(isNearScrollBottom({ scrollHeight: 1000, scrollTop: 700, clientHeight: 300 })).toBeTrue();
    });

    it('keeps the chat sticky during small runtime/reasoning height changes', () => {
        expect(isNearScrollBottom({ scrollHeight: 1050, scrollTop: 720, clientHeight: 300 })).toBeTrue();
    });

    it('does not force-scroll when the user is reading older messages', () => {
        expect(isNearScrollBottom({ scrollHeight: 1050, scrollTop: 660, clientHeight: 300 })).toBeFalse();
    });
});
