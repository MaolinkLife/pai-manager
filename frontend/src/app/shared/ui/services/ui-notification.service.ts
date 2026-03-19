import { Injectable } from '@angular/core';
import {
    NotificationOptions,
    NotificationService,
} from '../../components/notification/notification.service';

@Injectable({ providedIn: 'root' })
export class UiNotificationService {
    constructor(private readonly notificationService: NotificationService) {}

    open(options: NotificationOptions): void {
        this.notificationService.open(options);
    }

    success(message: string, title?: string): void {
        this.open({ type: 'success', message, title, autoClose: true });
    }

    error(message: string, title?: string): void {
        this.open({ type: 'error', message, title, autoClose: true });
    }
}
