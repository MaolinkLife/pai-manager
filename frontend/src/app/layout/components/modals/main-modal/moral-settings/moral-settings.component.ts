import { ChangeDetectorRef, Component, OnInit } from '@angular/core';
import {
    UntypedFormArray,
    UntypedFormBuilder,
    UntypedFormGroup,
    Validators,
} from '@angular/forms';
import { BehaviorSubject } from 'rxjs';
import { finalize, take } from 'rxjs/operators';
import { ApiService } from '../../../../../core/services/api.service';
import { ConfigService } from '../../../../../core/services/config.service';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';

@Component({
    selector: 'app-moral-settings',
    templateUrl: './moral-settings.component.html',
    styleUrls: ['./moral-settings.component.less']
})
export class MoralSettingsComponent implements OnInit {
    moralForm: UntypedFormGroup;
    isLoading$ = new BehaviorSubject<boolean>(true);
    originalConfig: any = {};
    ollamaModelOptions: UiSelectOption[] = [
        { value: '', label: 'Модели не найдены', disabled: true },
    ];
    private readonly defaultMoralSystemPrompt = `You are the MoralMatrix governor. Your output augments an AI companion's emotional behaviour. Receive the current evaluation payload (JSON) and respond with STRICT JSON containing guidance.`;

    constructor(
        private fb: UntypedFormBuilder,
        private apiService: ApiService,
        private configService: ConfigService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.moralForm = this.createForm();
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.loadConfig();
        this.loadOllamaModels();
        this.moralForm.get('activeProvider')?.valueChanges.subscribe((provider: string) => {
            const normalized = this.normalizeProvider(provider);
            if (normalized !== provider) {
                this.moralForm.get('activeProvider')?.setValue(normalized, { emitEvent: false });
            }
            this.toggleFallbackControls(normalized);
        });
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            enabled: [true],
            activeProvider: ['ollama', Validators.required],
            fallbackHeuristic: [true],
            fallbackOllama: [true],
            fallbackOpenrouter: [false],
            fallbackLlamaCpp: [false],
            releaseAfterUse: [true],
            systemPrompt: [this.defaultMoralSystemPrompt, Validators.required],
            providers: this.fb.group({
                ollama: this.fb.group({
                    model: ['', Validators.required],
                    temperature: [0.6, [Validators.min(0), Validators.max(2)]],
                    maxTokens: [512, [Validators.min(1), Validators.max(4096)]],
                    thinking: [false],
                }),
                openrouter: this.fb.group({
                    apiKey: [''],
                    model: ['', Validators.required],
                    temperature: [0.6, [Validators.min(0), Validators.max(2)]],
                    maxTokens: [512, [Validators.min(1), Validators.max(4096)]],
                }),
                llamaCpp: this.fb.group({
                    enabled: [false],
                    baseUrl: ['http://127.0.0.1:8080'],
                    model: [''],
                    temperature: [0.6, [Validators.min(0), Validators.max(2)]],
                    maxTokens: [512, [Validators.min(1), Validators.max(4096)]],
                    requestTimeout: [120, [Validators.min(1), Validators.max(600)]],
                }),
            }),
            // 0.8.0 — Wave 1: emotional core extensions
            decay: this.fb.group({
                enabled: [true],
                globalRate: [0.05, [Validators.min(0), Validators.max(1)]],
            }),
            forgiveness: this.fb.group({
                enabled: [true],
                compensatingTonesCsv: [''],
                softenableEmotionsCsv: [''],
                deltaPerEvent: [0.1, [Validators.min(0), Validators.max(1)]],
                lookbackDays: [14, [Validators.min(1), Validators.max(365)]],
            }),
            scars: this.fb.group({
                enabled: [false],
                triggers: this.fb.array([]),
            }),
            innerVoice: this.fb.group({
                enabled: [true],
                maxTokens: [80, [Validators.min(1), Validators.max(1024)]],
                temperature: [0.7, [Validators.min(0), Validators.max(2)]],
                language: [''],
            }),
        });
    }

    private createScarTriggerGroup(initial?: any): UntypedFormGroup {
        return this.fb.group({
            name: [initial?.name ?? '', Validators.required],
            intentsCsv: [(initial?.intents ?? []).join(', ')],
            tonesCsv: [(initial?.tones ?? []).join(', ')],
            keywordsCsv: [(initial?.keywords ?? []).join(', ')],
            persistenceFloor: [
                initial?.persistenceFloor ?? 0.4,
                [Validators.min(0), Validators.max(1)],
            ],
            intensityBoost: [
                initial?.intensityBoost ?? 0.2,
                [Validators.min(0), Validators.max(1)],
            ],
        });
    }

    get scarsTriggersArray(): UntypedFormArray {
        return this.moralForm.get('scars.triggers') as UntypedFormArray;
    }

    addScarTrigger(): void {
        this.scarsTriggersArray.push(this.createScarTriggerGroup());
        this.moralForm.markAsDirty();
    }

    removeScarTrigger(index: number): void {
        this.scarsTriggersArray.removeAt(index);
        this.moralForm.markAsDirty();
    }

    private csvToArray(value: any): string[] {
        return String(value || '')
            .split(',')
            .map((part) => part.trim())
            .filter((part) => part.length > 0);
    }

    private loadConfig(): void {
        this.isLoading$.next(true);

        this.configService
            .getConfig$()
            .pipe(
                take(1),
                finalize(() => this.isLoading$.next(false))
            )
            .subscribe({
                next: (config: any) => {
                    const moral = config?.moral || {};
                    const providers = moral.providers || {};

                    this.moralForm.patchValue({
                        enabled: moral.enabled ?? true,
                        activeProvider: this.normalizeProvider(moral.activeProvider || 'ollama'),
                        fallbackHeuristic: (moral.fallbackOrder || []).includes('heuristic'),
                        fallbackOllama: (moral.fallbackOrder || []).includes('ollama'),
                        fallbackOpenrouter: (moral.fallbackOrder || []).includes('openrouter'),
                        fallbackLlamaCpp: (moral.fallbackOrder || []).includes('llama_cpp'),
                        releaseAfterUse: moral.releaseAfterUse ?? true,
                        systemPrompt: moral.systemPrompt || this.defaultMoralSystemPrompt,
                    });

                    const providersGroup = this.moralForm.get('providers') as UntypedFormGroup;
                    const ollamaGroup = providersGroup.get('ollama') as UntypedFormGroup;
                    const openrouterGroup = providersGroup.get('openrouter') as UntypedFormGroup;

                    if (providers.ollama) {
                        ollamaGroup.patchValue({
                            model: providers.ollama.model || '',
                            temperature: providers.ollama.temperature ?? 0.6,
                            maxTokens: providers.ollama.maxTokens ?? providers.ollama.max_tokens ?? 512,
                            thinking: providers.ollama.thinking ?? false,
                        });
                    }

                    if (providers.openrouter) {
                        openrouterGroup.patchValue({
                            apiKey: providers.openrouter.apiKey || providers.openrouter.api_key || '',
                            model: providers.openrouter.model || '',
                            temperature: providers.openrouter.temperature ?? 0.6,
                            maxTokens: providers.openrouter.maxTokens ?? providers.openrouter.max_tokens ?? 512,
                        });
                    }

                    const llamaCppGroup = providersGroup.get('llamaCpp') as UntypedFormGroup;
                    const llamaCppRaw = providers.llamaCpp || providers.llama_cpp;
                    if (llamaCppRaw) {
                        llamaCppGroup.patchValue({
                            enabled: llamaCppRaw.enabled ?? false,
                            baseUrl:
                                llamaCppRaw.baseUrl || llamaCppRaw.base_url || 'http://127.0.0.1:8080',
                            model: llamaCppRaw.model || '',
                            temperature: llamaCppRaw.temperature ?? 0.6,
                            maxTokens:
                                llamaCppRaw.maxTokens ?? llamaCppRaw.max_tokens ?? 512,
                            requestTimeout:
                                llamaCppRaw.requestTimeout ?? llamaCppRaw.request_timeout ?? 120,
                        });
                    }

                    // 0.8.0 — Wave 1 sections
                    const decay = moral.decay || {};
                    this.moralForm.get('decay')!.patchValue({
                        enabled: decay.enabled ?? true,
                        globalRate: decay.globalRate ?? decay.global_rate ?? 0.05,
                    });

                    const forgiveness = moral.forgiveness || {};
                    this.moralForm.get('forgiveness')!.patchValue({
                        enabled: forgiveness.enabled ?? true,
                        compensatingTonesCsv: (
                            forgiveness.compensatingTones ?? forgiveness.compensating_tones ?? []
                        ).join(', '),
                        softenableEmotionsCsv: (
                            forgiveness.softenableEmotions ?? forgiveness.softenable_emotions ?? []
                        ).join(', '),
                        deltaPerEvent: forgiveness.deltaPerEvent ?? forgiveness.delta_per_event ?? 0.1,
                        lookbackDays: forgiveness.lookbackDays ?? forgiveness.lookback_days ?? 14,
                    });

                    const scars = moral.scars || {};
                    this.moralForm.get('scars')!.patchValue({
                        enabled: scars.enabled ?? false,
                    });
                    // Rebuild triggers FormArray
                    const triggersArray = this.scarsTriggersArray;
                    while (triggersArray.length > 0) {
                        triggersArray.removeAt(0);
                    }
                    const incomingTriggers = Array.isArray(scars.triggers) ? scars.triggers : [];
                    incomingTriggers.forEach((trig: any) => {
                        triggersArray.push(this.createScarTriggerGroup({
                            name: trig?.name,
                            intents: trig?.intents ?? [],
                            tones: trig?.tones ?? [],
                            keywords: trig?.keywords ?? [],
                            persistenceFloor: trig?.persistenceFloor ?? trig?.persistence_floor,
                            intensityBoost: trig?.intensityBoost ?? trig?.intensity_boost,
                        }));
                    });

                    const innerVoice = moral.innerVoice || moral.inner_voice || {};
                    this.moralForm.get('innerVoice')!.patchValue({
                        enabled: innerVoice.enabled ?? true,
                        maxTokens: innerVoice.maxTokens ?? innerVoice.max_tokens ?? 80,
                        temperature: innerVoice.temperature ?? 0.7,
                        language: innerVoice.language ?? '',
                    });

                    this.originalConfig = this.buildMoralConfigFromForm();
                    this.toggleFallbackControls(this.activeProvider);
                    this.ensureCurrentOllamaModelOption();
                    this.cdr.markForCheck();
                },
                error: (error) => {
                    console.error('Error loading moral config:', error);
                    this.notificationService.open({
                        title: 'Error',
                        type: 'error',
                        message: 'Failed to load Moral Matrix configuration',
                        autoClose: true,
                    });
                    this.cdr.markForCheck();
                },
            });
    }

    private loadOllamaModels(): void {
        this.apiService.getOllamaModels$().pipe(take(1)).subscribe({
            next: (models: string[]) => {
                const cleaned = (Array.isArray(models) ? models : [])
                    .map((item) => String(item || '').trim())
                    .filter((item) => item.length > 0);
                if (cleaned.length > 0) {
                    this.ollamaModelOptions = cleaned.map((model) => ({ value: model, label: model }));
                    this.ensureCurrentOllamaModelOption();
                    this.cdr.markForCheck();
                    return;
                }
                this.ollamaModelOptions = [{ value: '', label: 'Модели не найдены', disabled: true }];
                this.ensureCurrentOllamaModelOption();
                this.cdr.markForCheck();
            },
            error: () => {
                this.ollamaModelOptions = [{ value: '', label: 'Модели не найдены', disabled: true }];
                this.ensureCurrentOllamaModelOption();
                this.cdr.markForCheck();
            },
        });
    }

    private ensureCurrentOllamaModelOption(): void {
        const current = String(this.providersForm.get('ollama.model')?.value || '').trim();
        if (!current || this.ollamaModelOptions.some((item) => item.value === current)) {
            return;
        }
        this.ollamaModelOptions = [{ value: current, label: current }, ...this.ollamaModelOptions];
    }

    private toggleFallbackControls(activeProvider: string): void {
        const provider = this.normalizeProvider(activeProvider);
        const controls: Record<string, any> = {
            heuristic: this.moralForm.get('fallbackHeuristic'),
            ollama: this.moralForm.get('fallbackOllama'),
            openrouter: this.moralForm.get('fallbackOpenrouter'),
            llama_cpp: this.moralForm.get('fallbackLlamaCpp'),
        };
        Object.keys(controls).forEach((key) => {
            const ctrl = controls[key];
            if (!ctrl) return;
            if (key === provider) {
                ctrl.disable({ emitEvent: false });
                ctrl.setValue(false, { emitEvent: false });
            } else {
                ctrl.enable({ emitEvent: false });
            }
        });
    }

    saveChanges(): void {
        const changes = this.getChanges();
        if (Object.keys(changes).length === 0) {
            return;
        }

        this.configService.updateConfig$({ moral: changes }).subscribe({
            next: () => {
                this.notificationService.open({
                    title: 'Success',
                    type: 'success',
                    message: 'Moral Matrix settings updated successfully',
                    autoClose: true,
                });
                this.originalConfig = this.buildMoralConfigFromForm();
                this.moralForm.markAsPristine();
            },
            error: (error) => {
                console.error('Error updating moral settings:', error);
                this.notificationService.open({
                    title: 'Error',
                    type: 'error',
                    message: 'Failed to update Moral Matrix settings',
                    autoClose: true,
                });
            },
        });
    }

    private buildMoralConfigFromForm(): any {
        const formValue = this.moralForm.getRawValue();
        const activeProvider = this.normalizeProvider(formValue.activeProvider);
        const fallbackOrder: string[] = [];

        if (formValue.fallbackHeuristic && activeProvider !== 'heuristic') {
            fallbackOrder.push('heuristic');
        }
        if (formValue.fallbackOllama && activeProvider !== 'ollama') {
            fallbackOrder.push('ollama');
        }
        if (formValue.fallbackOpenrouter && activeProvider !== 'openrouter') {
            fallbackOrder.push('openrouter');
        }
        if (formValue.fallbackLlamaCpp && activeProvider !== 'llama_cpp') {
            fallbackOrder.push('llama_cpp');
        }

        const providers = {
            heuristic: {},
            ollama: {
                model: formValue.providers.ollama.model,
                temperature: Number(formValue.providers.ollama.temperature),
                maxTokens: Number(formValue.providers.ollama.maxTokens),
                thinking: Boolean(formValue.providers.ollama.thinking),
            },
            openrouter: {
                apiKey: formValue.providers.openrouter.apiKey,
                model: formValue.providers.openrouter.model,
                temperature: Number(formValue.providers.openrouter.temperature),
                maxTokens: Number(formValue.providers.openrouter.maxTokens),
            },
            llamaCpp: {
                enabled: Boolean(formValue.providers.llamaCpp?.enabled),
                baseUrl: String(formValue.providers.llamaCpp?.baseUrl || ''),
                model: String(formValue.providers.llamaCpp?.model || ''),
                temperature: Number(formValue.providers.llamaCpp?.temperature ?? 0.6),
                maxTokens: Number(formValue.providers.llamaCpp?.maxTokens ?? 512),
                requestTimeout: Number(formValue.providers.llamaCpp?.requestTimeout ?? 120),
            },
        };

        const triggers = (formValue.scars?.triggers || []).map((trig: any) => ({
            name: String(trig.name || '').trim(),
            intents: this.csvToArray(trig.intentsCsv),
            tones: this.csvToArray(trig.tonesCsv),
            keywords: this.csvToArray(trig.keywordsCsv),
            persistenceFloor: Number(trig.persistenceFloor ?? 0.4),
            intensityBoost: Number(trig.intensityBoost ?? 0.2),
        }));

        return {
            enabled: formValue.enabled,
            activeProvider,
            fallbackOrder,
            releaseAfterUse: !!formValue.releaseAfterUse,
            systemPrompt: String(formValue.systemPrompt || '').trim(),
            providers,
            decay: {
                enabled: !!formValue.decay?.enabled,
                globalRate: Number(formValue.decay?.globalRate ?? 0.05),
            },
            forgiveness: {
                enabled: !!formValue.forgiveness?.enabled,
                compensatingTones: this.csvToArray(formValue.forgiveness?.compensatingTonesCsv),
                softenableEmotions: this.csvToArray(formValue.forgiveness?.softenableEmotionsCsv),
                deltaPerEvent: Number(formValue.forgiveness?.deltaPerEvent ?? 0.1),
                lookbackDays: Number(formValue.forgiveness?.lookbackDays ?? 14),
            },
            scars: {
                enabled: !!formValue.scars?.enabled,
                triggers,
            },
            innerVoice: {
                enabled: !!formValue.innerVoice?.enabled,
                maxTokens: Number(formValue.innerVoice?.maxTokens ?? 80),
                temperature: Number(formValue.innerVoice?.temperature ?? 0.7),
                language: String(formValue.innerVoice?.language ?? '').trim(),
            },
        };
    }

    private getChanges(): any {
        const current = this.buildMoralConfigFromForm();
        const original = this.originalConfig || {};
        return this.deepDiff(original, current) || {};
    }

    private deepDiff(original: any, current: any): any {
        if (Array.isArray(current)) {
            const originalArray = Array.isArray(original) ? original : [];
            if (JSON.stringify(current) === JSON.stringify(originalArray)) {
                return undefined;
            }
            return current;
        }

        if (current !== null && typeof current === 'object') {
            const diff: Record<string, any> = {};

            Object.keys(current).forEach((key) => {
                const value = this.deepDiff(original ? original[key] : undefined, current[key]);
                if (value !== undefined) {
                    diff[key] = value;
                }
            });

            return Object.keys(diff).length > 0 ? diff : undefined;
        }

        if (current !== original) {
            return current;
        }

        return undefined;
    }

    hasChanges(): boolean {
        return Object.keys(this.getChanges()).length > 0;
    }

    get providersForm(): UntypedFormGroup {
        return this.moralForm.get('providers') as UntypedFormGroup;
    }

    get activeProvider(): string {
        return this.normalizeProvider(this.moralForm.get('activeProvider')?.value);
    }

    get isOllamaActive(): boolean {
        return this.activeProvider === 'ollama';
    }

    get isOpenrouterActive(): boolean {
        return this.activeProvider === 'openrouter';
    }

    get activeProviderOptions(): UiSelectOption[] {
        return [
            { value: 'ollama', label: 'Ollama' },
            { value: 'openrouter', label: 'OpenRouter' },
            { value: 'llama_cpp', label: 'llama.cpp' },
            { value: 'heuristic', label: this.localizationService.t('moralSettings.heuristicProvider') },
        ];
    }

    get isLlamaCppActive(): boolean {
        return this.activeProvider === 'llama_cpp';
    }

    private normalizeProvider(value: any): string {
        return String(value || '').trim().toLowerCase();
    }
}
