import { NgModule } from '@angular/core';
import { CommonModule } from '@angular/common';

import { ChatRoutingModule } from './chat-routing.module';
import { ChatComponent } from './chat.component';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { ApiService } from '../../core/services/api.service';
import { ConfigService } from '../../core/services/config.service';
import { SharedModule } from '../../shared/shared.module';
import { ChatComposerComponent } from './components/chat-composer/chat-composer.component';
import { ChatMessageComponent } from './components/chat-message/chat-message.component';
import { ChatRuntimeBlockComponent } from './components/chat-runtime-block/chat-runtime-block.component';
import { ChatStoreModule } from './store';


@NgModule({ declarations: [
        ChatComponent,
        ChatComposerComponent,
        ChatMessageComponent,
        ChatRuntimeBlockComponent
    ], imports: [CommonModule,
        ChatRoutingModule,
        FormsModule,
        ReactiveFormsModule,
        SharedModule,
        ChatStoreModule], providers: [
        ApiService,
        ConfigService,
        provideHttpClient(withInterceptorsFromDi()),
    ] })
export class ChatModule { }
