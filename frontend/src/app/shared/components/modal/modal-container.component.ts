import {
    Component,
    Inject,
    ViewChild,
    ViewContainerRef,
    ComponentFactoryResolver,
    AfterViewInit,
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    NgZone
} from '@angular/core';
import { ModalRef } from './modal-ref';

@Component({
    selector: 'app-modal-container',
    templateUrl: './modal-container.component.html',
    styleUrls: ['./modal-container.component.less'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class ModalContainerComponent implements AfterViewInit {
    @ViewChild('dynamicComponent', { read: ViewContainerRef }) vcr!: ViewContainerRef;

    title: string = '';
    appearance: 'fullscreen' | 'default' = 'fullscreen';

    constructor(
        @Inject('MODAL_DATA') public data: any,
        public modalRef: ModalRef,
        private cfr: ComponentFactoryResolver,
        private cdr: ChangeDetectorRef,
        private ngZone: NgZone
    ) { }

    ngAfterViewInit() {
        this.ngZone.run(() => {
            if (this.data?.appearance === 'default' || this.data?.appearance === 'fullscreen') {
                this.appearance = this.data.appearance;
            }

            if (this.data?.component) {
                const factory = this.cfr.resolveComponentFactory(this.data.component);
                const compRef = this.vcr.createComponent(factory);
                if (this.data?.data && typeof this.data.data === 'object') {
                    Object.assign(compRef.instance as object, this.data.data as object);
                }
                compRef.changeDetectorRef.detectChanges();
            }

            if (this.data?.title) {
                this.title = this.data.title;
                this.cdr.detectChanges();
            }
        });
    }

    onBackdropClick() {
        if (this.data?.dismissOnBackdrop !== false) {
            this.modalRef.closeModal();
        }
    }
}
