import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { ThemeModule } from './components/theme/theme.module';
import { IconsToolbarModule } from './components/icons-toolbar/icons-toolbar.module';
import { TranslationModule } from './pipes/translation/translation.module';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';

@NgModule({
    imports: [
        CommonModule,
        ThemeModule,
        IconsToolbarModule,
        TranslationModule.forRoot(),
        FormsModule,
        ReactiveFormsModule,
    ],
    exports: [
        ThemeModule,
        IconsToolbarModule,
        TranslationModule,
        FormsModule,
        ReactiveFormsModule,
    ]
})
export class SharedModule { }
