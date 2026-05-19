export function hasOpenThinkingBlock(content: string): boolean {
    if (!content) {
        return false;
    }
    const lower = content.toLowerCase();
    const openIdx = lower.lastIndexOf('<think>');
    if (openIdx === -1) {
        return false;
    }
    const closeIdx = lower.lastIndexOf('</think>');
    return closeIdx < openIdx;
}

export function hasClosedThinkingBlock(content: string): boolean {
    if (!content) {
        return false;
    }
    const lower = content.toLowerCase();
    const openIdx = lower.indexOf('<think>');
    const closeIdx = lower.lastIndexOf('</think>');
    return openIdx !== -1 && closeIdx > openIdx;
}

export function shouldCollapseThinkingBlock(isStreaming: boolean, content: string): boolean {
    return isStreaming && hasClosedThinkingBlock(content);
}

export function getStreamingRenderContent(content: string): string {
    return String(content || '');
}
