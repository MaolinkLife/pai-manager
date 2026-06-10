import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { DebugRoutingModule } from './debug-routing.module';
import { DebugComponent } from './debug.component';
import { LoggerService } from '../../core/services/logger.service';
import { SharedModule } from '../../shared/shared.module';


@NgModule({
    declarations: [
        DebugComponent
    ],
    imports: [
        CommonModule,
        FormsModule,
        DebugRoutingModule,
        SharedModule
    ],
    providers: [
        LoggerService,
    ]
})
export class DebugModule { }
