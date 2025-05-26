import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { ThemeModule } from './components/theme/theme.module';

@NgModule({
    imports: [
        CommonModule,
        ThemeModule
    ],
    exports: [
        ThemeModule
    ]
})
export class SharedModule { }
