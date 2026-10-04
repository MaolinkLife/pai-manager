import { Inject, Injectable, Provider, DOCUMENT } from '@angular/core';
import { EVENT_MANAGER_PLUGINS, EventManagerPlugin } from '@angular/platform-browser';

/**
 * Event-name modifier plugins for host listeners and templates:
 *
 *   (keydown.arrowDown.prevent) — preventDefault before the handler
 *   (click.stop)                — stopPropagation before the handler
 *   (mousemove.silent)          — listener attached outside the Angular zone
 *
 * Each plugin strips its suffix and delegates back to the EventManager, so
 * modifiers compose with native Angular event syntax.
 */

const PREVENT_SUFFIX = '.prevent';
const STOP_SUFFIX = '.stop';
const SILENT_SUFFIX = '.silent';

@Injectable()
export class UiPreventEventPlugin extends EventManagerPlugin {
    constructor(@Inject(DOCUMENT) documentRef: Document) {
        super(documentRef);
    }

    supports(event: string): boolean {
        return event.endsWith(PREVENT_SUFFIX);
    }

    addEventListener(element: HTMLElement, event: string, handler: Function): Function {
        return this.manager.addEventListener(
            element,
            event.slice(0, -PREVENT_SUFFIX.length),
            (domEvent: Event) => {
                domEvent.preventDefault();
                handler(domEvent);
            },
        );
    }
}

@Injectable()
export class UiStopEventPlugin extends EventManagerPlugin {
    constructor(@Inject(DOCUMENT) documentRef: Document) {
        super(documentRef);
    }

    supports(event: string): boolean {
        return event.endsWith(STOP_SUFFIX);
    }

    addEventListener(element: HTMLElement, event: string, handler: Function): Function {
        return this.manager.addEventListener(
            element,
            event.slice(0, -STOP_SUFFIX.length),
            (domEvent: Event) => {
                domEvent.stopPropagation();
                handler(domEvent);
            },
        );
    }
}

@Injectable()
export class UiSilentEventPlugin extends EventManagerPlugin {
    constructor(@Inject(DOCUMENT) documentRef: Document) {
        super(documentRef);
    }

    supports(event: string): boolean {
        return event.endsWith(SILENT_SUFFIX);
    }

    addEventListener(element: HTMLElement, event: string, handler: Function): Function {
        let teardown: Function = () => undefined;

        this.manager.getZone().runOutsideAngular(() => {
            teardown = this.manager.addEventListener(
                element,
                event.slice(0, -SILENT_SUFFIX.length),
                handler,
            );
        });

        return () => teardown();
    }
}

export const UI_EVENT_MODIFIER_PLUGINS: Provider[] = [
    { provide: EVENT_MANAGER_PLUGINS, useClass: UiPreventEventPlugin, multi: true },
    { provide: EVENT_MANAGER_PLUGINS, useClass: UiStopEventPlugin, multi: true },
    { provide: EVENT_MANAGER_PLUGINS, useClass: UiSilentEventPlugin, multi: true },
];
