import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { SharedModule } from '../../shared/shared.module';
import { SandboxRoutingModule } from './sandbox-routing.module';
import { SandboxComponent } from './sandbox.component';

@NgModule({
    declarations: [SandboxComponent],
    imports: [CommonModule, SharedModule, SandboxRoutingModule],
})
export class SandboxModule {}
