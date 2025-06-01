import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { ThemeModule } from './components/theme/theme.module';
import { IconsToolbarModule } from './components/icons-toolbar/icons-toolbar.module';

@NgModule({
    imports: [
        CommonModule,
        ThemeModule,
        IconsToolbarModule
    ],
    exports: [
        ThemeModule,
        IconsToolbarModule,
    ]
})
export class SharedModule { }
