import { Component, ViewChild, ViewContainerRef } from '@angular/core';

@Component({
    selector: 'app-modal-wrapper',
    template: `<ng-template #modalContainer></ng-template>`,
    standalone: false
})
export class ModalWrapperComponent {
    @ViewChild('modalContainer', { read: ViewContainerRef, static: true })
    container!: ViewContainerRef;
}
