// main-modal.component.ts
import { Component, Inject, OnInit } from '@angular/core';
import { ModalRef } from '../../../../shared/components/modal/modal-ref';
import { LocalizationService } from '../../../../shared/pipes/translation/localization.service';

@Component({
    selector: 'app-main-modal',
    templateUrl: './main-modal.component.html',
    styleUrls: ['./main-modal.component.less']
})
export class MainModalComponent implements OnInit {
    modalRef: ModalRef;

    tabs = [
        { key: 'lorebook', labelKey: 'settingsSidebar.lorebook' },
        { key: 'voice', labelKey: 'settingsSidebar.tts' },
        { key: 'audio', labelKey: 'settingsSidebar.audio' },
        { key: 'vision', labelKey: 'settingsSidebar.vision' },
        { key: 'rag', labelKey: 'settingsSidebar.rag' },
        { key: 'analyzer', labelKey: 'settingsSidebar.analyzer' },
        { key: 'moral', labelKey: 'settingsSidebar.moral' },
        { key: 'compliance', labelKey: 'settingsSidebar.compliance' },
        { key: 'generate', labelKey: 'settingsSidebar.generation' },
        { key: 'persona', labelKey: 'settingsSidebar.persona' },
        { key: 'media', labelKey: 'settingsSidebar.media' },
        { key: 'social', labelKey: 'settingsSidebar.social' },
        { key: 'core', labelKey: 'settingsSidebar.core' },
        { key: 'system', labelKey: 'settingsSidebar.system' }
    ];

    activeView = 'lorebook';

    constructor(
        @Inject('MODAL_DATA') public data: any,
        private _modalRef: ModalRef,
        private localizationService: LocalizationService
    ) {
        this.modalRef = _modalRef;
    }

    ngOnInit(): void {
        this.localizationService.init();
        console.log({ action: 'MainModalComponent ngOnInit' });
    }

    t(key: string): string {
        return this.localizationService.t(key);
    }

    selectView(view: string): void {
        this.activeView = view;
    }

    close(): void {
        this.modalRef.closeModal({ closed: true });
    }
}
