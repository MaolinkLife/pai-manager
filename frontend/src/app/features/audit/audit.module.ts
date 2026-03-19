import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { SharedModule } from '../../shared/shared.module';
import { AuditRoutingModule } from './audit-routing.module';
import { AuditComponent } from './audit.component';

@NgModule({
    declarations: [AuditComponent],
    imports: [CommonModule, SharedModule, AuditRoutingModule],
})
export class AuditModule {}
