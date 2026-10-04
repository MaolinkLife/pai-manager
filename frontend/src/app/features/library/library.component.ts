import { Component, ElementRef, OnInit, ViewChild } from '@angular/core';
import { finalize } from 'rxjs/operators';
import { LibraryItem } from '../../core/models/library.model';
import { LibraryService } from '../../core/services/library.service';
import {
    KnowledgeCollection,
    KnowledgeFile,
    KnowledgeService,
} from '../../core/services/knowledge.service';
import { NotificationService } from '../../shared/components/notification/notification.service';

type LibraryViewMode = 'grid' | 'list';
type LibraryCategory = 'all' | 'image' | 'document' | 'audio' | 'video' | 'other';
type LibraryPageTab = 'files' | 'collections';

@Component({
    selector: 'app-library',
    templateUrl: './library.component.html',
    styleUrls: ['./library.component.less'],
    standalone: false
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
    pageTab: LibraryPageTab = 'files';

    // §7.3.3 — knowledge collections
    collections: KnowledgeCollection[] = [];
    collectionsLoading = false;
    activeCollection: KnowledgeCollection | null = null;
    collectionFiles: KnowledgeFile[] = [];
    filesLoading = false;
    newCollectionName = '';
    newCollectionDescription = '';
    creatingCollection = false;
    pickerOpen = false;
    pickerItems: LibraryItem[] = [];
    pickerLoading = false;
    addingMediaIds = new Set<string>();
    busyFileIds = new Set<string>();
    reindexingCollection = false;

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
        private knowledgeService: KnowledgeService,
        private notificationService: NotificationService
    ) {}

    ngOnInit(): void {
        this.load();
    }

    switchTab(tab: LibraryPageTab): void {
        if (this.pageTab === tab) {
            return;
        }
        this.pageTab = tab;
        if (tab === 'collections' && !this.collections.length) {
            this.loadCollections();
        }
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

    // ----------------------------------------------------------- collections

    loadCollections(): void {
        this.collectionsLoading = true;
        this.knowledgeService
            .collections$()
            .pipe(finalize(() => (this.collectionsLoading = false)))
            .subscribe({
                next: (collections) => {
                    this.collections = collections;
                    if (this.activeCollection) {
                        this.activeCollection =
                            collections.find((item) => item.id === this.activeCollection!.id) || null;
                    }
                },
                error: () => this.notifyError('Не удалось загрузить коллекции.'),
            });
    }

    createCollection(): void {
        const name = this.newCollectionName.trim();
        if (!name || this.creatingCollection) {
            return;
        }
        this.creatingCollection = true;
        this.knowledgeService
            .createCollection$(name, this.newCollectionDescription.trim())
            .pipe(finalize(() => (this.creatingCollection = false)))
            .subscribe({
                next: (collection) => {
                    this.newCollectionName = '';
                    this.newCollectionDescription = '';
                    this.collections = [collection, ...this.collections];
                    this.openCollection(collection);
                },
                error: () => this.notifyError('Не удалось создать коллекцию.'),
            });
    }

    openCollection(collection: KnowledgeCollection): void {
        this.activeCollection = collection;
        this.loadCollectionFiles(collection.id);
    }

    closeCollection(): void {
        this.activeCollection = null;
        this.collectionFiles = [];
        this.pickerOpen = false;
    }

    private loadCollectionFiles(collectionId: string): void {
        this.filesLoading = true;
        this.knowledgeService
            .files$(collectionId)
            .pipe(finalize(() => (this.filesLoading = false)))
            .subscribe({
                next: (files) => (this.collectionFiles = files),
                error: () => this.notifyError('Не удалось загрузить файлы коллекции.'),
            });
    }

    toggleCollectionEnabled(collection: KnowledgeCollection, event?: Event): void {
        event?.stopPropagation();
        this.knowledgeService
            .updateCollection$(collection.id, { enabled: !collection.enabled })
            .subscribe({
                next: (updated) => {
                    this.collections = this.collections.map((item) =>
                        item.id === updated.id ? updated : item
                    );
                    if (this.activeCollection?.id === updated.id) {
                        this.activeCollection = updated;
                    }
                },
                error: () => this.notifyError('Не удалось обновить коллекцию.'),
            });
    }

    deleteCollection(collection: KnowledgeCollection, event?: Event): void {
        event?.stopPropagation();
        if (!window.confirm(`Удалить коллекцию «${collection.name}» вместе с индексом?`)) {
            return;
        }
        this.knowledgeService.deleteCollection$(collection.id).subscribe({
            next: () => {
                this.collections = this.collections.filter((item) => item.id !== collection.id);
                if (this.activeCollection?.id === collection.id) {
                    this.closeCollection();
                }
            },
            error: () => this.notifyError('Не удалось удалить коллекцию.'),
        });
    }

    // ----------------------------------------------------- files in collection

    openPicker(): void {
        this.pickerOpen = true;
        this.pickerLoading = true;
        this.libraryService
            .list$({ q: '', category: 'document', limit: 300 })
            .pipe(finalize(() => (this.pickerLoading = false)))
            .subscribe({
                next: (response) => {
                    const used = new Set(this.collectionFiles.map((file) => file.media_id));
                    this.pickerItems = (response.items || []).filter((item) => !used.has(item.id));
                },
                error: () => this.notifyError('Не удалось загрузить документы библиотеки.'),
            });
    }

    closePicker(): void {
        this.pickerOpen = false;
        this.pickerItems = [];
    }

    addFromPicker(item: LibraryItem): void {
        const collection = this.activeCollection;
        if (!collection || this.addingMediaIds.has(item.id)) {
            return;
        }
        this.addingMediaIds.add(item.id);
        this.knowledgeService.addFile$(collection.id, item.id).subscribe({
            next: (file) => {
                this.addingMediaIds.delete(item.id);
                this.pickerItems = this.pickerItems.filter((entry) => entry.id !== item.id);
                this.collectionFiles = [file, ...this.collectionFiles.filter((entry) => entry.id !== file.id)];
                this.bumpFileCount(collection.id, 1);
                if (file.status === 'error') {
                    this.notifyError(`«${file.name}»: ${file.error || 'ошибка индексации'}`);
                }
            },
            error: (error) => {
                this.addingMediaIds.delete(item.id);
                this.notifyError(error?.error?.detail || `Не удалось добавить «${item.name}».`);
            },
        });
    }

    reindexFile(file: KnowledgeFile): void {
        if (this.busyFileIds.has(file.id)) {
            return;
        }
        this.busyFileIds.add(file.id);
        this.knowledgeService.reindexFile$(file.id).subscribe({
            next: (updated) => {
                this.busyFileIds.delete(file.id);
                this.collectionFiles = this.collectionFiles.map((entry) =>
                    entry.id === updated.id ? updated : entry
                );
            },
            error: () => {
                this.busyFileIds.delete(file.id);
                this.notifyError('Переиндексация не удалась.');
            },
        });
    }

    removeFile(file: KnowledgeFile): void {
        if (this.busyFileIds.has(file.id)) {
            return;
        }
        this.busyFileIds.add(file.id);
        this.knowledgeService.removeFile$(file.id).subscribe({
            next: () => {
                this.busyFileIds.delete(file.id);
                this.collectionFiles = this.collectionFiles.filter((entry) => entry.id !== file.id);
                this.bumpFileCount(file.collection_id, -1);
            },
            error: () => {
                this.busyFileIds.delete(file.id);
                this.notifyError('Не удалось убрать файл из коллекции.');
            },
        });
    }

    reindexCollection(): void {
        const collection = this.activeCollection;
        if (!collection || this.reindexingCollection) {
            return;
        }
        this.reindexingCollection = true;
        this.knowledgeService
            .reindexCollection$(collection.id)
            .pipe(finalize(() => (this.reindexingCollection = false)))
            .subscribe({
                next: (files) => (this.collectionFiles = files),
                error: () => this.notifyError('Переиндексация коллекции не удалась.'),
            });
    }

    private bumpFileCount(collectionId: string, delta: number): void {
        this.collections = this.collections.map((item) =>
            item.id === collectionId
                ? { ...item, file_count: Math.max(0, item.file_count + delta) }
                : item
        );
        if (this.activeCollection?.id === collectionId) {
            this.activeCollection = {
                ...this.activeCollection,
                file_count: Math.max(0, this.activeCollection.file_count + delta),
            };
        }
    }

    fileStatusLabel(file: KnowledgeFile): string {
        switch (file.status) {
            case 'indexed':
                return `${file.chunk_count} фрагм.`;
            case 'error':
                return 'ошибка';
            default:
                return 'в очереди';
        }
    }

    private notifyError(message: string): void {
        this.notificationService.open({ type: 'error', message, autoClose: true });
    }

    trackByCollection(_index: number, collection: KnowledgeCollection): string {
        return collection.id;
    }

    trackByKnowledgeFile(_index: number, file: KnowledgeFile): string {
        return file.id;
    }

    // ------------------------------------------------------------------ files

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
