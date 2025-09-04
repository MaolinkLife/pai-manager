import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { ThemeModule } from './components/theme/theme.module';
import { IconsToolbarModule } from './components/icons-toolbar/icons-toolbar.module';
import { TranslationModule } from './pipes/translation/translation.module';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { ModalModule } from './components/modal/modal.module';

@NgModule({
    imports: [
        CommonModule,
        ThemeModule,
        IconsToolbarModule,
        TranslationModule.forRoot(),
        FormsModule,
        ReactiveFormsModule,
        ModalModule,
    ],
    exports: [
        ThemeModule,
        IconsToolbarModule,
        TranslationModule,
        FormsModule,
        ReactiveFormsModule,
        ModalModule,
    ]
})
export class SharedModule { }
