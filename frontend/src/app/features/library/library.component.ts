import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { finalize } from 'rxjs/operators';
import { LibraryItem } from '../../core/models/library.model';
import { LibraryService } from '../../core/services/library.service';
import { NotificationService } from '../../shared/components/notification/notification.service';

type LibraryViewMode = 'grid' | 'list';
type LibraryCategory = 'all' | 'image' | 'document' | 'audio' | 'video' | 'other';

@Component({
    selector: 'app-library',
    templateUrl: './library.component.html',
    styleUrls: ['./library.component.less'],
})
export class LibraryComponent implements OnInit {
    @ViewChild('uploadInput') uploadInput?: ElementRef<HTMLInputElement>;

    items: LibraryItem[] = [];
    selected = new Set<string>();
    activeItem: LibraryItem | null = null;
    activeContent = '';
    loading = false;
    uploading = false;
    contentLoading = false;
    query = '';
    category: LibraryCategory = 'all';
    viewMode: LibraryViewMode = 'grid';
    selectionMode = false;
    total = 0;

    readonly categories: Array<{ value: LibraryCategory; label: string }> = [
        { value: 'all', label: 'Все' },
        { value: 'image', label: 'Картинки' },
        { value: 'document', label: 'Документы' },
        { value: 'audio', label: 'Аудио' },
        { value: 'video', label: 'Видео' },
        { value: 'other', label: 'Другое' },
    ];

    constructor(
        private libraryService: LibraryService,
        private notificationService: NotificationService
    ) {}

    ngOnInit(): void {
        this.load();
    }

    load(): void {
        this.loading = true;
        this.libraryService
            .list$({ q: this.query.trim(), category: this.category, limit: 300 })
            .pipe(finalize(() => (this.loading = false)))
            .subscribe({
                next: (response) => {
                    this.items = response.items || [];
                    this.total = response.total || this.items.length;
                    this.selected = new Set([...this.selected].filter((id) => this.items.some((item) => item.id === id)));
                },
                error: () => {
                    this.notificationService.open({
                        type: 'error',
                        message: 'Не удалось загрузить библиотеку.',
                        autoClose: true,
                    });
                },
            });
    }

    triggerUpload(): void {
        this.uploadInput?.nativeElement.click();
    }

    uploadFiles(event: Event): void {
        const input = event.target as HTMLInputElement;
        const files = Array.from(input.files || []);
        if (!files.length) {
            return;
        }
        this.uploading = true;
        let completed = 0;
        files.forEach((file) => {
            this.libraryService.upload$(file).subscribe({
                next: () => {
                    completed += 1;
                    if (completed === files.length) {
                        this.uploading = false;
                        input.value = '';
                        this.load();
                    }
                },
                error: () => {
                    completed += 1;
                    this.notificationService.open({
                        type: 'error',
                        message: `Не удалось загрузить ${file.name}.`,
                        autoClose: true,
                    });
                    if (completed === files.length) {
                        this.uploading = false;
                        input.value = '';
                        this.load();
                    }
                },
            });
        });
    }

    openItem(item: LibraryItem): void {
        this.activeItem = item;
        this.activeContent = '';
        if (this.isDocument(item)) {
            this.contentLoading = true;
            this.libraryService
                .content$(item.id)
                .pipe(finalize(() => (this.contentLoading = false)))
                .subscribe({
                    next: (response) => {
                        this.activeContent = response.content || '';
                    },
                    error: () => {
                        this.activeContent = 'Предпросмотр для этого файла недоступен.';
                    },
                });
        }
    }

    closeViewer(): void {
        this.activeItem = null;
        this.activeContent = '';
        this.contentLoading = false;
    }

    toggleSelected(item: LibraryItem, event?: MouseEvent): void {
        event?.stopPropagation();
        if (!this.selectionMode) {
            this.selectionMode = true;
        }
        const next = new Set(this.selected);
        if (next.has(item.id)) {
            next.delete(item.id);
        } else {
            next.add(item.id);
        }
        this.selected = next;
    }

    toggleSelectionMode(): void {
        this.selectionMode = !this.selectionMode;
        if (!this.selectionMode) {
            this.selected = new Set();
        }
    }

    deleteItem(item: LibraryItem, event?: MouseEvent): void {
        event?.stopPropagation();
        this.libraryService.delete$(item.id).subscribe({
            next: () => {
                this.selected.delete(item.id);
                if (this.activeItem?.id === item.id) {
                    this.closeViewer();
                }
                this.load();
            },
            error: () => {
                this.notificationService.open({
                    type: 'error',
                    message: 'Не удалось удалить файл.',
                    autoClose: true,
                });
            },
        });
    }

    download(item: LibraryItem, event?: MouseEvent): void {
        event?.stopPropagation();
        window.open(this.libraryService.resolveUrl(item), '_blank');
    }

    getItemUrl(item: LibraryItem): string {
        return this.libraryService.resolveUrl(item);
    }

    isImage(item: LibraryItem | null): boolean {
        return item?.category === 'image' || !!item?.mimeType?.startsWith('image/');
    }

    isDocument(item: LibraryItem | null): boolean {
        return item?.category === 'document' || !!item?.mimeType?.startsWith('text/');
    }

    isMarkdown(item: LibraryItem | null): boolean {
        const name = item?.name?.toLowerCase() || '';
        return name.endsWith('.md') || name.endsWith('.markdown');
    }

    formatSize(size: number | null | undefined): string {
        const value = Number(size || 0);
        if (value >= 1024 * 1024) {
            return `${(value / 1024 / 1024).toFixed(2)} MB`;
        }
        if (value >= 1024) {
            return `${(value / 1024).toFixed(1)} KB`;
        }
        return `${value} B`;
    }

    formatDate(value: string | null | undefined): string {
        if (!value) {
            return '—';
        }
        return new Date(value).toLocaleString();
    }

    extension(item: LibraryItem): string {
        const parts = (item.name || '').split('.');
        return parts.length > 1 ? parts.pop()!.toUpperCase() : item.category.toUpperCase();
    }

    trackByItem(_index: number, item: LibraryItem): string {
        return item.id;
    }
}
