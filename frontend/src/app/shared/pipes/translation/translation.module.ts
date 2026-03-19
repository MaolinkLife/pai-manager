import { NgModule, ModuleWithProviders } from '@angular/core';
import { CommonModule } from '@angular/common';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';

import { TranslatePipe } from './translate.pipe';
import { LocalizationService } from './localization.service';

@NgModule({ declarations: [TranslatePipe],
    exports: [TranslatePipe], imports: [CommonModule], providers: [provideHttpClient(withInterceptorsFromDi())] })
export class TranslationModule {
    static forRoot(): ModuleWithProviders<TranslationModule> {
        return {
            ngModule: TranslationModule,
            providers: [LocalizationService]
        };
    }
}
