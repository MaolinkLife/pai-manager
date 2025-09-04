import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';

import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { SidebarComponent } from './layout/components/sidebar/sidebar.component';
import { HeaderComponent } from './layout/components/header/header.component';
import { LayoutComponent } from './layout/layout.component';
import { ThemeService } from './core/services/theme.service';
import { SharedModule } from './shared/shared.module';
import { HttpClient, HttpClientModule } from '@angular/common/http';
import { ConfigService } from './core/services/config.service';
import { MarkdownModule } from 'ngx-markdown';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { MemoryModalComponent } from './layout/components/modals/memory-modal/memory-modal.component';
import { MainModalComponent } from './layout/components/modals/main-modal/main-modal.component';
import { LorebookComponent } from './layout/components/modals/main-modal/lorebook/lorebook.component';

@NgModule({
    declarations: [
        AppComponent,
        SidebarComponent,
        HeaderComponent,
        LayoutComponent,
        MemoryModalComponent,
        MainModalComponent,
        LorebookComponent,
    ],
    imports: [
        BrowserModule,
        AppRoutingModule,
        SharedModule,
        HttpClientModule,
        BrowserAnimationsModule,
        MarkdownModule.forRoot({ loader: HttpClient }),
    ],
    providers: [ThemeService, ConfigService],
    bootstrap: [AppComponent],
    entryComponents: [
        MemoryModalComponent,
        MainModalComponent,
    ]
})
export class AppModule { }
