import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { CustomSvgComponent } from './custom-svg.component';

@NgModule({
    declarations: [CustomSvgComponent],
    imports: [CommonModule],
    exports: [CustomSvgComponent]
})
export class CustomSvgModule { }
