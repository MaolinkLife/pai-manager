export interface Message {
    id: string | null;
    role: 'user' | 'assistant';
    content: string;
    timestamp: string;
}
