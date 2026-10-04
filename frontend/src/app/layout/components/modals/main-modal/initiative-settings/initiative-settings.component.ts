import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { InitiativeConfig } from '../../../../../core/models/project-config.model';
import { ConfigService } from '../../../../../core/services/config.service';
import { pickChangedFields } from '../../../../../core/utils/changed-fields';
import { mapInitiativeDtoToModel } from '../../../../../core/utils/initiative-config-mapper';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';

/**
 * Initiative — when PAI writes first. A global screen, not a channel one:
 * the switch here gates every channel, while what
 * concerns a single channel stays in that channel's settings.
 */
@Component({
    selector: 'app-initiative-settings',
    templateUrl: './initiative-settings.component.html',
    styleUrls: ['./initiative-settings.component.less'],
    standalone: false
})
export class InitiativeSettingsComponent implements OnInit {
    initiativeForm: UntypedFormGroup;
    isLoading$ = new BehaviorSubject<boolean>(true);
    loadFailed = false;
    private originalSnapshot: InitiativeConfig = mapInitiativeDtoToModel();

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.initiativeForm = this.createForm();
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.loadConfig();
    }

    private createForm(): UntypedFormGroup {
        const defaults = mapInitiativeDtoToModel();
        return this.fb.group({
            enabled: [defaults.enabled],
            chat: this.fb.group({
                enabled: [defaults.chat.enabled],
            }),
            selfie: this.fb.group({
                enabled: [defaults.selfie.enabled],
                chance: [defaults.selfie.chance, [Validators.required, Validators.min(0), Validators.max(1)]],
            }),
        });
    }

    private loadConfig(): void {
        this.isLoading$.next(true);
        this.configService
            .getConfig$()
            .pipe(
                take(1),
                finalize(() => this.isLoading$.next(false)),
            )
            .subscribe((config) => {
                // Without the stored values a save could not tell what changed.
                this.loadFailed = !config;
                if (config) {
                    this.initiativeForm.reset(config.initiative ?? mapInitiativeDtoToModel());
                    this.originalSnapshot = this.buildSnapshot();
                } else {
                    this.notify('error', 'initiativeSettings.loadError');
                }
                this.cdr.markForCheck();
            });
    }

    private buildSnapshot(): InitiativeConfig {
        return JSON.parse(JSON.stringify(this.initiativeForm.getRawValue()));
    }

    hasChanges(): boolean {
        return !this.loadFailed && Object.keys(pickChangedFields(this.buildSnapshot(), this.originalSnapshot)).length > 0;
    }

    saveChanges(): void {
        if (this.initiativeForm.invalid || !this.hasChanges()) {
            return;
        }
        const current = this.buildSnapshot();
        const initiative = pickChangedFields(current, this.originalSnapshot);
        this.configService.updateConfig$({ initiative }).subscribe({
            next: () => {
                this.originalSnapshot = current;
                this.initiativeForm.markAsPristine();
                this.notify('success', 'initiativeSettings.saved');
                this.cdr.markForCheck();
            },
            error: () => this.notify('error', 'initiativeSettings.saveError'),
        });
    }

    private notify(type: 'success' | 'error', messageKey: string): void {
        this.notificationService.open({
            title: type === 'success' ? 'Success' : 'Error',
            type,
            message: this.localizationService.t(messageKey),
            autoClose: true,
        });
    }
}
