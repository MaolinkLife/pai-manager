import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ApiService, ModelIndexEntry } from '../../../../../core/services/api.service';
import { ModalRef } from '../../../../../shared/components/modal/modal-ref';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';

/**
 * What one model can do, marked by the owner (model index).
 *
 * Opened from the models tab with the model's index entry. Saving writes the
 * owner's marks to the index and closes with the updated entry; marks equal to
 * what Ollama declares follow Ollama again (the server decides that).
 */
@Component({
    selector: 'app-model-capabilities-modal',
    templateUrl: './model-capabilities-modal.component.html',
    styleUrls: ['./model-capabilities-modal.component.less'],
    standalone: false
})
export class ModelCapabilitiesModalComponent implements OnInit {
    /** Set by the modal service from `data`. */
    entry!: ModelIndexEntry;
    capabilityKeys: string[] = [];

    form!: UntypedFormGroup;
    saving = false;
    saveError = '';

    constructor(
        private fb: UntypedFormBuilder,
        private apiService: ApiService,
        private localizationService: LocalizationService,
        private modalRef: ModalRef,
        private cdr: ChangeDetectorRef,
    ) {}

    ngOnInit(): void {
        const controls: Record<string, boolean> = {};
        this.capabilityKeys.forEach((key) => {
            controls[key] = this.entry.capabilities.includes(key);
        });
        this.form = this.fb.group(controls);
    }

    t(key: string): string {
        return this.localizationService.t(key);
    }

    isDeclared(key: string): boolean {
        return this.entry.declared.includes(key);
    }

    selected(): string[] {
        return this.capabilityKeys.filter((key) => !!this.form.value[key]);
    }

    differsFromOllama(): boolean {
        const selected = this.selected();
        const declared = this.entry.declared;
        return selected.length !== declared.length || selected.some((key) => !declared.includes(key));
    }

    /** Puts back the ticks Ollama declares; saving is still the owner's. */
    resetToOllama(): void {
        this.capabilityKeys.forEach((key) => this.form.get(key)?.setValue(this.isDeclared(key)));
    }

    save(): void {
        if (this.saving) {
            return;
        }
        this.saving = true;
        this.saveError = '';
        this.apiService.setModelCapabilities$(this.entry.name, this.selected(), this.entry.provider).subscribe((entry) => {
            this.saving = false;
            if (entry) {
                this.modalRef.closeModal(entry);
                return;
            }
            this.saveError = this.t('settingsPage.models.capabilitiesSaveError');
            this.cdr.markForCheck();
        });
    }

    cancel(): void {
        this.modalRef.closeModal();
    }

    trackByKey(_index: number, key: string): string {
        return key;
    }
}
