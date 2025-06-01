import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { DebugRoutingModule } from './debug-routing.module';
import { DebugComponent } from './debug.component';
import { LoggerService } from '../../core/services/logger.service';


@NgModule({
    declarations: [
        DebugComponent
    ],
    imports: [
        CommonModule,
        DebugRoutingModule
    ],
    providers: [
        LoggerService,
    ]
})
export class DebugModule { }
