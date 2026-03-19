import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ModalWrapperComponent } from './modal-wrapper.component';
import { ModalContainerComponent } from './modal-container.component';
import { ModalService } from './modal.service';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { CustomSvgModule } from '../custom-svg/custom-svg.module';

@NgModule({
    declarations: [ModalWrapperComponent, ModalContainerComponent],
    imports: [CommonModule, FormsModule, ReactiveFormsModule, CustomSvgModule],
    exports: [ModalWrapperComponent],
    providers: [ModalService],
})
export class ModalModule { }
