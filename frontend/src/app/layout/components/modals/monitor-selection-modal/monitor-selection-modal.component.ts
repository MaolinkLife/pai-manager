import { Component, Inject, OnInit } from '@angular/core';
import { catchError, map, startWith } from 'rxjs/operators';
import { Observable, of } from 'rxjs';
import { ResourcesService } from '../../../../core/services/resources.service';
import { ModalRef } from '../../../../shared/components/modal/modal-ref';

interface Monitor {
    index: number;
    width: number;
    height: number;
    left: number;
    top: number;
    preview: string;
}

interface MonitorResponse {
    status: string;
    monitors: Monitor[];
}

@Component({
    selector: 'app-monitor-selection-modal',
    templateUrl: './monitor-selection-modal.component.html',
    styleUrls: ['./monitor-selection-modal.component.less']
})
export class MonitorSelectionModalComponent implements OnInit {
    selectedMonitor: number = 0;
    error: string | null = null;
    statusText = '';

    monitors$: Observable<Monitor[] | null> = of(null);

    constructor(
        @Inject('MODAL_DATA') public data: any,
        private modalRef: ModalRef,
        private resourcesService: ResourcesService
    ) {
        this.selectedMonitor = this.getPayload()?.selectedMonitor ?? 0;
    }

    ngOnInit(): void {
        this.loadMonitorData();
    }

    private cleanBase64String(base64String: string): string {
        if (!base64String) return '';

        let cleanString = base64String.replace(/^data:image\/[a-z]+;base64,/, '');
        cleanString = cleanString.replace(/\s/g, '');

        return cleanString;
    }

    private loadMonitorData(): void {
        const payload = this.getPayload();

        if (payload?.monitors) {
            this.selectedMonitor = payload?.selectedMonitor ?? 0;
            const cleanedMonitors = payload.monitors.map((monitor: any) => ({
                ...monitor,
                preview: this.cleanBase64String(monitor.preview)
            }));
            this.monitors$ = of(cleanedMonitors);
            this.statusText = this.getStatusText(cleanedMonitors.length);
            return;
        }

        this.monitors$ = this.resourcesService.getMonitorScreens$().pipe(
            map((response: MonitorResponse) => {
                if (response && response.monitors) {
                    const cleanedMonitors = response.monitors.map((monitor: any) => ({
                        ...monitor,
                        preview: this.cleanBase64String(monitor.preview)
                    }));
                    this.statusText = this.getStatusText(cleanedMonitors.length);
                    return cleanedMonitors;
                }

                throw new Error('No monitor data received');
            }),
            startWith(null),
            catchError(error => {
                this.error = 'Failed to load monitor information';
                this.statusText = 'Monitor data is unavailable';
                return of([]);
            })
        );
    }

    private getPayload(): any {
        return this.data?.data ?? this.data ?? {};
    }

    private getStatusText(count: number): string {
        if (count === 1) {
            return '1 monitor detected';
        }
        return `${count} monitors detected`;
    }

    trackByIndex(index: number, item: Monitor): number {
        return item?.index ?? index;
    }

    onImageError(index: number, event: Event): void {
        const image = event.target as HTMLImageElement | null;
        image?.classList.add('monitor-card__image--hidden');
    }

    selectMonitor(index: number): void {
        this.selectedMonitor = index;
    }

    confirmSelection(): void {
        const payload = this.getPayload();

        if (payload?.onSelect && typeof payload.onSelect === 'function') {
            payload.onSelect({ selectedMonitor: this.selectedMonitor });
        }

        this.modalRef.closeModal({ selectedMonitor: this.selectedMonitor });
    }

    close(): void {
        this.modalRef.closeModal();
    }
}
