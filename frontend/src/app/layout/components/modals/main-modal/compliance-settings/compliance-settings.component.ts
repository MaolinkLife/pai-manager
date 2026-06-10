import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup, Validators } from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { ConfigService } from '../../../../../core/services/config.service';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';

/**
 * Compliance settings (0.9.0 Wave 2 / 0.9.1 UI pass).
 *
 * Surfaces toggles + tuning numbers for the 5 post-generation checks that
 * live at the top level of the project config:
 *   • Validator     (§3.5)
 *   • Language guard (§3.5-bis)
 *   • Confidence    (§3.8)
 *   • Factuality    (§3.9)
 *   • Self-Watcher  (§3.7)
 *
 * Each section maps to its own top-level config key, so `saveChanges`
 * sends a multi-key PATCH body. Defaults mirror constants/default_config.py.
 */
@Component({
    selector: 'app-compliance-settings',
    templateUrl: './compliance-settings.component.html',
    styleUrls: ['./compliance-settings.component.less'],
})
export class ComplianceSettingsComponent implements OnInit {
    complianceForm: UntypedFormGroup;
    isLoading$ = new BehaviorSubject<boolean>(true);
    originalSnapshot: any = {};

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.complianceForm = this.createForm();
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.loadConfig();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            validator: this.fb.group({
                enabled: [false],
                threshold: [0.7, [Validators.min(0), Validators.max(1)]],
                maxTokens: [256, [Validators.min(1), Validators.max(4096)]],
                temperature: [0.0, [Validators.min(0), Validators.max(2)]],
                instructionCharLimit: [4000, [Validators.min(0)]],
                outputCharLimit: [4000, [Validators.min(0)]],
            }),
            languageGuard: this.fb.group({
                enabled: [false],
                minDominance: [0.7, [Validators.min(0), Validators.max(1)]],
                minOutputChars: [40, [Validators.min(0)]],
            }),
            confidence: this.fb.group({
                enabled: [false],
                threshold: [0.5, [Validators.min(0), Validators.max(1)]],
                maxTokens: [64, [Validators.min(1), Validators.max(4096)]],
                temperature: [0.0, [Validators.min(0), Validators.max(2)]],
                userCharLimit: [2000, [Validators.min(0)]],
                outputCharLimit: [4000, [Validators.min(0)]],
            }),
            factuality: this.fb.group({
                enabled: [false],
                gateOnLowConfidence: [true],
                topK: [3, [Validators.min(1), Validators.max(50)]],
                minSimilarity: [0.6, [Validators.min(0), Validators.max(1)]],
                maxClaims: [6, [Validators.min(1), Validators.max(100)]],
                claimMinLength: [3, [Validators.min(1), Validators.max(100)]],
            }),
            selfWatcher: this.fb.group({
                enabled: [false],
                mismatchThreshold: [0.5, [Validators.min(0), Validators.max(1)]],
                nightlyReflectionEnabled: [true],
                lookbackDays: [7, [Validators.min(1), Validators.max(365)]],
                maxEventsInCluster: [20, [Validators.min(1), Validators.max(500)]],
                llmMaxTokens: [220, [Validators.min(1), Validators.max(4096)]],
                llmTemperature: [0.5, [Validators.min(0), Validators.max(2)]],
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
            .subscribe({
                next: (config: any) => {
                    if (config) {
                        this.patchFromConfig(config);
                    }
                    this.originalSnapshot = this.buildSnapshot();
                    this.cdr.markForCheck();
                },
                error: () => {
                    this.notificationService.open({
                        title: 'Error',
                        type: 'error',
                        message: 'Failed to load compliance configuration',
                        autoClose: true,
                    });
                    this.cdr.markForCheck();
                },
            });
    }

    private patchFromConfig(config: any): void {
        const validator = config.validator || {};
        this.complianceForm.get('validator')!.patchValue({
            enabled: validator.enabled ?? false,
            threshold: validator.threshold ?? 0.7,
            maxTokens: validator.maxTokens ?? validator.max_tokens ?? 256,
            temperature: validator.temperature ?? 0.0,
            instructionCharLimit:
                validator.instructionCharLimit ?? validator.instruction_char_limit ?? 4000,
            outputCharLimit:
                validator.outputCharLimit ?? validator.output_char_limit ?? 4000,
        });

        const lg = config.languageGuard || config.language_guard || {};
        this.complianceForm.get('languageGuard')!.patchValue({
            enabled: lg.enabled ?? false,
            minDominance: lg.minDominance ?? lg.min_dominance ?? 0.7,
            minOutputChars: lg.minOutputChars ?? lg.min_output_chars ?? 40,
        });

        const conf = config.confidence || {};
        this.complianceForm.get('confidence')!.patchValue({
            enabled: conf.enabled ?? false,
            threshold: conf.threshold ?? 0.5,
            maxTokens: conf.maxTokens ?? conf.max_tokens ?? 64,
            temperature: conf.temperature ?? 0.0,
            userCharLimit: conf.userCharLimit ?? conf.user_char_limit ?? 2000,
            outputCharLimit: conf.outputCharLimit ?? conf.output_char_limit ?? 4000,
        });

        const fact = config.factuality || {};
        this.complianceForm.get('factuality')!.patchValue({
            enabled: fact.enabled ?? false,
            gateOnLowConfidence:
                fact.gateOnLowConfidence ?? fact.gate_on_low_confidence ?? true,
            topK: fact.topK ?? fact.top_k ?? 3,
            minSimilarity: fact.minSimilarity ?? fact.min_similarity ?? 0.6,
            maxClaims: fact.maxClaims ?? fact.max_claims ?? 6,
            claimMinLength: fact.claimMinLength ?? fact.claim_min_length ?? 3,
        });

        const sw = config.selfWatcher || config.self_watcher || {};
        this.complianceForm.get('selfWatcher')!.patchValue({
            enabled: sw.enabled ?? false,
            mismatchThreshold: sw.mismatchThreshold ?? sw.mismatch_threshold ?? 0.5,
            nightlyReflectionEnabled:
                sw.nightlyReflectionEnabled ?? sw.nightly_reflection_enabled ?? true,
            lookbackDays: sw.lookbackDays ?? sw.lookback_days ?? 7,
            maxEventsInCluster:
                sw.maxEventsInCluster ?? sw.max_events_in_cluster ?? 20,
            llmMaxTokens: sw.llmMaxTokens ?? sw.llm_max_tokens ?? 220,
            llmTemperature: sw.llmTemperature ?? sw.llm_temperature ?? 0.5,
        });
    }

    private buildSnapshot(): any {
        return JSON.parse(JSON.stringify(this.complianceForm.getRawValue()));
    }

    hasChanges(): boolean {
        return JSON.stringify(this.buildSnapshot()) !== JSON.stringify(this.originalSnapshot);
    }

    saveChanges(): void {
        if (!this.hasChanges()) {
            return;
        }
        const current = this.buildSnapshot();
        const updateData: any = {
            validator: current.validator,
            languageGuard: current.languageGuard,
            confidence: current.confidence,
            factuality: current.factuality,
            selfWatcher: current.selfWatcher,
        };
        this.configService.updateConfig$(updateData).subscribe({
            next: () => {
                this.notificationService.open({
                    title: 'Success',
                    type: 'success',
                    message: 'Compliance settings updated',
                    autoClose: true,
                });
                this.originalSnapshot = current;
                this.complianceForm.markAsPristine();
                this.cdr.markForCheck();
            },
            error: (err) => {
                console.error('Error updating compliance settings:', err);
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to update compliance settings',
                    autoClose: true,
                });
            },
        });
    }
}
