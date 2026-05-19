import {
    getStreamingRenderContent,
    hasClosedThinkingBlock,
    hasOpenThinkingBlock,
    shouldCollapseThinkingBlock,
} from './chat-thinking.util';

describe('chat thinking rendering', () => {
    it('keeps closed reasoning in render content while the answer is streaming', () => {
        const content = '<think>reasoning</think>answer chunk';

        expect(getStreamingRenderContent(content)).toBe(content);
        expect(hasClosedThinkingBlock(content)).toBeTrue();
        expect(shouldCollapseThinkingBlock(true, content)).toBeTrue();
    });

    it('detects open reasoning blocks without collapsing them', () => {
        const content = '<think>still reasoning';

        expect(hasOpenThinkingBlock(content)).toBeTrue();
        expect(hasClosedThinkingBlock(content)).toBeFalse();
        expect(shouldCollapseThinkingBlock(true, content)).toBeFalse();
    });

    it('does not collapse completed messages just because they contain reasoning', () => {
        expect(shouldCollapseThinkingBlock(false, '<think>done</think>answer')).toBeFalse();
    });
});
