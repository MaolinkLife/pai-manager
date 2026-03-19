import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { SharedModule } from '../../shared/shared.module';
import { MemoryRoutingModule } from './memory-routing.module';
import { MemoryComponent } from './memory.component';

@NgModule({
    declarations: [MemoryComponent],
    imports: [CommonModule, SharedModule, MemoryRoutingModule],
})
export class MemoryModule {}
