import {
    ChangeDetectionStrategy,
    ChangeDetectorRef,
    Component,
    Input,
    OnChanges,
    SimpleChanges
} from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { IconService } from '../../services/icon.service';

@Component({
    selector: 'app-custom-svg',
    templateUrl: './custom-svg.component.html',
    styleUrls: ['./custom-svg.component.less'],
    changeDetection: ChangeDetectionStrategy.OnPush
})
export class CustomSvgComponent implements OnChanges {
    @Input() name = '';
    @Input() size = 16;
    @Input() title = '';

    iconMarkup: SafeHtml | null = null;
    private requestId = 0;

    constructor(
        private iconService: IconService,
        private sanitizer: DomSanitizer,
        private cdr: ChangeDetectorRef
    ) { }

    ngOnChanges(changes: SimpleChanges): void {
        if (changes['name'] || changes['size']) {
            this.resolveIcon();
        }
    }

    private async resolveIcon(): Promise<void> {
        const iconName = (this.name || '').trim();
        const iconSize = this.size;
        const requestId = ++this.requestId;

        if (!iconName) {
            this.iconMarkup = null;
            this.cdr.markForCheck();
            return;
        }

        const icon = await this.iconService.resolve(iconName, iconSize);
        if (requestId !== this.requestId) {
            return;
        }

        this.iconMarkup = icon ? this.sanitizer.bypassSecurityTrustHtml(icon) : null;
        this.cdr.markForCheck();
    }
}
