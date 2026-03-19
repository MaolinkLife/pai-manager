import { Injectable, ApplicationRef, ComponentFactoryResolver, Injector, EmbeddedViewRef, ComponentRef, TemplateRef } from '@angular/core';
import { NotificationRef } from './notification-ref';
import { NotificationContainerComponent } from './notification-container.component';
import { NOTIFICATION_DATA } from './notification.tokens';

export interface NotificationOptions {
    message?: any;
    title?: any;
    type: 'success' | 'error' | 'warning' | 'info';
    duration?: number;
    template?: TemplateRef<any>;
    autoClose?: boolean;
}

@Injectable({ providedIn: 'root' })
export class NotificationService {
    private container: HTMLElement;

    constructor(
        private appRef: ApplicationRef,
        private cfr: ComponentFactoryResolver,
        private injector: Injector
    ) {
        this.container = this.createContainer();
    }

    open(options: NotificationOptions) {
        const normalized = this.normalizeOptions(options);
        const notificationRef = new NotificationRef(() => this.destroy(componentRef));

        const injector = Injector.create({
            providers: [
                { provide: NOTIFICATION_DATA, useValue: normalized },
                { provide: NotificationRef, useValue: notificationRef }
            ],
            parent: this.injector
        });

        const factory = this.cfr.resolveComponentFactory(NotificationContainerComponent);
        const componentRef = factory.create(injector);

        this.appRef.attachView(componentRef.hostView);
        const domElem = (componentRef.hostView as EmbeddedViewRef<any>).rootNodes[0] as HTMLElement;

        this.container.appendChild(domElem);

        return notificationRef;
    }

    private destroy(componentRef: ComponentRef<any>) {
        this.appRef.detachView(componentRef.hostView);
        componentRef.destroy();
    }

    private createContainer(): HTMLElement {
        const container = document.createElement('div');
        container.id = 'notification-container';
        container.style.position = 'fixed';
        container.style.top = '20px';
        container.style.right = '20px';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
        return container;
    }

    private normalizeOptions(options: NotificationOptions): NotificationOptions {
        const type = options?.type || 'info';
        const title = this.extractText(options?.title) || this.defaultTitle(type);
        const message = this.extractText(options?.message);

        return {
            ...options,
            type,
            title,
            message,
        };
    }

    private defaultTitle(type: NotificationOptions['type']): string {
        if (type === 'success') {
            return 'Success';
        }
        if (type === 'error') {
            return 'Error';
        }
        if (type === 'warning') {
            return 'Warning';
        }
        return 'Info';
    }

    private extractText(value: any): string {
        if (value === null || value === undefined) {
            return '';
        }

        if (typeof value === 'string') {
            const trimmed = value.trim();
            return trimmed && trimmed !== '[object Object]' ? trimmed : '';
        }

        if (typeof value === 'number' || typeof value === 'boolean') {
            return String(value);
        }

        if (Array.isArray(value)) {
            return value
                .map((item) => this.extractText(item))
                .filter(Boolean)
                .join('; ');
        }

        if (typeof value === 'object') {
            const candidates = [
                value?.detail,
                value?.message,
                value?.msg,
                value?.error,
                value?.description,
                value?.title,
                value?.statusText,
            ];
            for (const candidate of candidates) {
                const parsed = this.extractText(candidate);
                if (parsed) {
                    return parsed;
                }
            }
        }

        return '';
    }
}
