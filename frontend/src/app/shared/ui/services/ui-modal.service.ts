import { Injectable, Type } from '@angular/core';
import { ModalRef } from '../../components/modal/modal-ref';
import { ModalService } from '../../components/modal/modal.service';

@Injectable({ providedIn: 'root' })
export class UiModalService {
    constructor(private readonly modalService: ModalService) {}

    open<T>(
        component: Type<T>,
        options: { data?: any; title?: string } = {}
    ): ModalRef {
        return this.modalService.open(component, options);
    }
}
