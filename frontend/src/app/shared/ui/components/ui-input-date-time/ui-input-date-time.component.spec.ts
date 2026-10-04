import { ElementRef } from '@angular/core';
import { UiInputDateTimeComponent } from './ui-input-date-time.component';

describe('UiInputDateTimeComponent: a click on the document', () => {
    let host: HTMLElement;
    let inner: HTMLElement;
    let touched: number;

    function create(): UiInputDateTimeComponent {
        host = document.createElement('div');
        inner = document.createElement('span');
        host.appendChild(inner);
        touched = 0;
        const component = new UiInputDateTimeComponent(new ElementRef(host));
        component.registerOnTouched(() => touched++);
        component.open = true;
        return component;
    }

    it('closes the calendar when the click lands outside', () => {
        const component = create();

        component.onDocumentClick(document.createElement('div'));

        expect(component.open).toBe(false);
        expect(touched).toBe(1);
    });

    it('keeps the calendar open when the click lands inside', () => {
        const component = create();

        component.onDocumentClick(inner);

        expect(component.open).toBe(true);
        expect(touched).toBe(0);
    });

    it('treats a click without a target node as outside', () => {
        const component = create();

        component.onDocumentClick(null);

        expect(component.open).toBe(false);
    });

    it('does nothing while the calendar is closed', () => {
        const component = create();
        component.open = false;

        component.onDocumentClick(document.createElement('div'));

        expect(touched).toBe(0);
    });
});
