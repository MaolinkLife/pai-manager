import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { ChatRoutingModule } from './chat-routing.module';
import { ChatComponent } from './chat.component';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { ApiService } from '../../core/services/api.service';
import { ConfigService } from '../../core/services/config.service';
import { SharedModule } from '../../shared/shared.module';


@NgModule({ declarations: [
        ChatComponent
    ], imports: [CommonModule,
        ChatRoutingModule,
        FormsModule,
        ReactiveFormsModule,
        SharedModule], providers: [
        ApiService,
        ConfigService,
        provideHttpClient(withInterceptorsFromDi()),
    ] })
export class ChatModule { }
