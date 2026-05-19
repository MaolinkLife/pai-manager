import { MessageMediaCategory } from './message.model';

export interface LibraryItem {
    id: string;
    name: string;
    fileName?: string;
    mimeType: string;
    size: number;
    category: MessageMediaCategory;
    description?: string;
    url: string;
    downloadUrl?: string;
    messageId?: string;
    createdAt?: string;
    updatedAt?: string;
    exists?: boolean;
}

export interface LibraryListResponse {
    status: string;
    items: LibraryItem[];
    total: number;
}

export interface LibraryContentResponse {
    status: string;
    item: LibraryItem;
    content: string;
}
