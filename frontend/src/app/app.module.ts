import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';

import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { SidebarComponent } from './layout/components/sidebar/sidebar.component';
import { HeaderComponent } from './layout/components/header/header.component';
import { LayoutComponent } from './layout/layout.component';
import { ThemeService } from './core/services/theme.service';
import { SharedModule } from './shared/shared.module';
import { HTTP_INTERCEPTORS, provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { ConfigService } from './core/services/config.service';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { MemoryModalComponent } from './layout/components/modals/memory-modal/memory-modal.component';
import { SettingsComponentsModule } from './layout/components/modals/main-modal/settings-components.module';
import { MonitorSelectionModalComponent } from './layout/components/modals/monitor-selection-modal/monitor-selection-modal.component';
import { AiEntityVisualizerComponent } from './layout/components/ai-entity-visualizer/ai-entity-visualizer.component';
import { AuthInterceptor } from './core/interceptors/auth.interceptor';


@NgModule({ declarations: [
        AppComponent,
        SidebarComponent,
        HeaderComponent,
        LayoutComponent,
        MemoryModalComponent,
        MonitorSelectionModalComponent,
        AiEntityVisualizerComponent,
    ],
    bootstrap: [AppComponent], imports: [BrowserModule,
        AppRoutingModule,
        SharedModule,
        SettingsComponentsModule,
        BrowserAnimationsModule], providers: [ThemeService, ConfigService, provideHttpClient(withInterceptorsFromDi()), {
            provide: HTTP_INTERCEPTORS,
            useClass: AuthInterceptor,
            multi: true
        }] })
export class AppModule { }
