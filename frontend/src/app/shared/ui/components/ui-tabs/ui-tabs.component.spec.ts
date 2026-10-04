import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { UiModule } from '../../ui.module';
import { UiTabsComponent } from './ui-tabs.component';

@Component({
    template: `
        <app-ui-tabs [(activeKey)]="active">
            <app-ui-tab key="general">General</app-ui-tab>
            <app-ui-tab key="off" [disabled]="true">Off</app-ui-tab>
            <app-ui-tab key="bridge">Bridge</app-ui-tab>
        </app-ui-tabs>
    `,
    imports: [UiModule],
})
class TabsHostComponent {
    active: string | null = 'general';
}

describe('UiTabsComponent', () => {
    let fixture: ComponentFixture<TabsHostComponent>;
    let host: TabsHostComponent;

    const buttons = (): HTMLButtonElement[] =>
        fixture.debugElement.queryAll(By.css('.ui-tab')).map((el) => el.nativeElement);

    const tabList = (): UiTabsComponent =>
        fixture.debugElement.query(By.directive(UiTabsComponent)).componentInstance;

    const pressKey = (key: string): void => {
        const list = fixture.debugElement.query(By.directive(UiTabsComponent)).nativeElement as HTMLElement;
        list.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
        fixture.detectChanges();
    };

    beforeEach(() => {
        TestBed.configureTestingModule({
            imports: [TabsHostComponent],
        });
        fixture = TestBed.createComponent(TabsHostComponent);
        host = fixture.componentInstance;
        fixture.detectChanges();
    });

    it('marks only the active tab as selected and reachable with Tab', () => {
        const [general, off, bridge] = buttons();

        expect(general.getAttribute('aria-selected')).toBe('true');
        expect(general.tabIndex).toBe(0);
        expect(off.tabIndex).toBe(-1);
        expect(bridge.getAttribute('aria-selected')).toBe('false');
        expect(bridge.tabIndex).toBe(-1);
    });

    it('activates a tab on click and reports it to the page', () => {
        buttons()[2].click();
        fixture.detectChanges();

        expect(host.active).toBe('bridge');
        expect(buttons()[2].classList).toContain('ui-tab--active');
        expect(buttons()[0].classList).not.toContain('ui-tab--active');
    });

    it('emits nothing for the already active tab or a disabled one', () => {
        const emitted: string[] = [];
        tabList().activeKeyChange.subscribe((key) => emitted.push(key));

        buttons()[0].click();
        tabList().select('off');

        expect(emitted).toEqual([]);
        expect(host.active).toBe('general');
    });

    it('skips disabled tabs with the arrow keys and wraps around', () => {
        pressKey('ArrowRight');
        expect(host.active).toBe('bridge');

        pressKey('ArrowRight');
        expect(host.active).toBe('general');

        pressKey('ArrowLeft');
        expect(host.active).toBe('bridge');
    });

    it('jumps to the first and last enabled tab with Home and End', () => {
        pressKey('End');
        expect(host.active).toBe('bridge');

        pressKey('Home');
        expect(host.active).toBe('general');
    });

    it('moves focus together with the keyboard selection', () => {
        pressKey('ArrowRight');

        expect(document.activeElement).toBe(buttons()[2]);
    });
});
