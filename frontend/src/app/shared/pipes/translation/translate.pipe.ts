import { ChangeDetectorRef, Pipe, PipeTransform, effect } from '@angular/core';
import { LocalizationService } from './localization.service';

@Pipe({
    name: 'translate',
    pure: false
})
export class TranslatePipe implements PipeTransform {
    private lastKey = '';
    private lastValue = '';

    constructor(
        private loc: LocalizationService,
        private cd: ChangeDetectorRef
    ) {
        effect(() => {
            this.loc.translationsState();
            if (this.lastKey) {
                this.lastValue = this.loc.t(this.lastKey);
            }
            this.cd.markForCheck();
        });
    }

    transform(key: string): string {
        if (key !== this.lastKey) {
            this.lastKey = key;
            this.lastValue = this.loc.t(key);
        }
        return this.lastValue;
    }
}
