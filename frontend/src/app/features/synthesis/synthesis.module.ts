import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { SharedModule } from '../../shared/shared.module';
import { SynthesisRoutingModule } from './synthesis-routing.module';
import { SynthesisComponent } from './synthesis.component';

@NgModule({
    declarations: [SynthesisComponent],
    imports: [CommonModule, SharedModule, SynthesisRoutingModule],
})
export class SynthesisModule {}
