import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IconsToolbarComponent } from './icons-toolbar.component';
import { CustomSvgModule } from '../custom-svg/custom-svg.module';

@NgModule({
    declarations: [IconsToolbarComponent],
    imports: [CommonModule, CustomSvgModule],
    exports: [IconsToolbarComponent],
    providers: [],
})
export class IconsToolbarModule { }
