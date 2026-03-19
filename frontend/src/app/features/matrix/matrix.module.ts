import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { SharedModule } from '../../shared/shared.module';
import { MatrixRoutingModule } from './matrix-routing.module';
import { MatrixComponent } from './matrix.component';

@NgModule({
    declarations: [MatrixComponent],
    imports: [CommonModule, SharedModule, MatrixRoutingModule],
})
export class MatrixModule {}
