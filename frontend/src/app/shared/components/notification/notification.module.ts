import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { NotificationContainerComponent } from './notification-container.component';
import { CustomSvgModule } from '../custom-svg/custom-svg.module';

@NgModule({
    declarations: [NotificationContainerComponent],
    imports: [CommonModule, CustomSvgModule]
})
export class NotificationModule { }
