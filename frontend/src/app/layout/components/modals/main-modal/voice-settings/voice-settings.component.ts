import { ChangeDetectorRef, Component, ElementRef, OnDestroy, OnInit, ViewChild } from '@angular/core';
import { FormBuilder, FormGroup } from '@angular/forms';
import { BehaviorSubject, Observable, forkJoin, of } from 'rxjs';
import { finalize, take } from 'rxjs/operators';

import { ConfigService } from '../../../../../core/services/config.service';
import { ResourcesService } from '../../../../../core/services/resources.service';
import { VoiceService, ImportVoiceResponse, VoiceProvidersResponse } from '../../../../../core/services/voice.service';
import { NotificationService } from '../../../../../shared/components/notification/notification.service';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';

interface AudioDevice {
    id: number;
    name: string;
}

interface AudioDevicesData {
    audioOutputs: AudioDevice[];
    windowsOutputs: AudioDevice[];
}

interface TTSProviderStatus {
    available: boolean;
    disabled: boolean;
    cooldown: number;
    lastFailureAt?: number | null;
    lastError?: string | null;
}

interface VoiceModuleOption {
    value: string;
    label: string;
    available: boolean;
    disabled: boolean;
    tooltip?: string;
}

interface LocalVoiceFileOption {
    name: string;
    path: string;
    summary?: {
        duration_seconds?: number;
        sample_rate?: number;
        channels?: number;
        codec?: string;
        size_bytes?: number;
        is_prepared_xtts?: boolean;
        is_xtts_compatible?: boolean;
        health?: string;
        hint?: string;
    };
}

interface LocalXttsModelOption {
    name: string;
    path: string;
    installed: boolean;
    downloadable: boolean;
    custom: boolean;
    status: string;
    progress: number;
    message: string;
    downloading: boolean;
}

interface LocalRvcModelOption {
    name: string;
    path: string;
}

interface PreviewChunkDebugRow {
    index: number;
    reason: string;
    length: number;
    text: string;
}

interface XttsVoicePreset {
    key: string;
    label: string;
    description: string;
    values: {
        voiceSimilarity: number;
        referenceWeight: number;
        speed: number;
        temperature: number;
        lengthPenalty: number;
        repetitionPenalty: number;
        topK: number;
        topP: number;
        gptCondLen: number;
        gptCondChunkLen: number;
        maxRefLen: number;
        soundNormRefs: boolean;
    };
}

@Component({
    selector: 'app-voice-settings',
    templateUrl: './voice-settings.component.html',
    styleUrls: ['./voice-settings.component.less'],
    standalone: false
})
export class VoiceSettingsComponent implements OnInit, OnDestroy {
    readonly xttsModelRoot = 'models/xtts';
    readonly recommendedChunkLengthRange = 'Recommended: 180-220. Default: 180. Lower values start speech earlier.';
    readonly prefetchChunksHint = 'How many audio chunks are prepared ahead while the current one is playing.';
    readonly prefetchDelayHint = 'Optional delay before preloading the next chunk (ms). Set 0 for maximum speed.';
    readonly volumeHint = 'Controls waifu playback loudness and local preview volume.';
    readonly voiceSimilarityHint = 'Macro control for how tightly XTTS should match the source speaker timbre.';
    readonly referenceWeightHint = 'Macro control for how strongly the reference sample should dominate generation.';
    readonly rvcF0MethodOptions = [
        { value: 'fcpe', label: 'FCPE' },
        { value: 'rmvpe', label: 'RMVPE' },
        { value: 'crepe', label: 'CREPE' },
        { value: 'pm', label: 'Parselmouth' },
        { value: 'dio', label: 'DIO' },
    ];
    readonly rvcEmbedderOptions = [
        { value: 'hubert', label: 'Hubert' },
        { value: 'contentvec', label: 'ContentVec' },
    ];
    readonly baseVoiceModules: VoiceModuleOption[] = [
        { value: 'coqui', label: 'XTTS V2', available: true, disabled: false },
        { value: 'elevenlabs', label: 'ElevenLabs', available: true, disabled: false },
        { value: 'edge', label: 'Edge TTS', available: true, disabled: false },
        { value: 'gtts', label: 'gTTS (Google)', available: true, disabled: false },
        { value: 'offline', label: 'Offline (pyttsx3)', available: true, disabled: false },
        { value: 'qwen', label: 'Qwen3-TTS (local)', available: true, disabled: false },
    ];
    readonly qwenDeviceOptions: UiSelectOption<string>[] = [
        { value: 'cuda', label: 'CUDA' },
        { value: 'cpu', label: 'CPU' },
    ];
    readonly qwenDtypeOptions: UiSelectOption<string>[] = [
        { value: 'bfloat16', label: 'bfloat16' },
        { value: 'float16', label: 'float16' },
        { value: 'float32', label: 'float32' },
    ];
    readonly coquiDeviceOptions: UiSelectOption<string>[] = [
        { value: 'cpu', label: 'CPU' },
        { value: 'cuda', label: 'CUDA' },
    ];
    readonly coquiLanguageOptions: UiSelectOption<string>[] = [
        { value: 'ru', label: 'ru' },
        { value: 'en', label: 'eng' },
    ];
    readonly xttsVoicePresets: XttsVoicePreset[] = [
        {
            key: 'maximumSimilarity',
            label: 'Maximum Similarity',
            description: 'Push XTTS toward the closest possible clone of the reference voice.',
            values: {
                voiceSimilarity: 0.95,
                referenceWeight: 0.95,
                speed: 1,
                temperature: 0.2,
                lengthPenalty: 1,
                repetitionPenalty: 2.1,
                topK: 50,
                topP: 0.8,
                gptCondLen: 24,
                gptCondChunkLen: 6,
                maxRefLen: 30,
                soundNormRefs: false,
            },
        },
        {
            key: 'similarityWithLiveliness',
            label: 'Similarity + Liveliness',
            description: 'Keep the voice close to the sample while allowing a bit more natural motion and expression.',
            values: {
                voiceSimilarity: 0.82,
                referenceWeight: 0.8,
                speed: 1,
                temperature: 0.32,
                lengthPenalty: 1,
                repetitionPenalty: 1.9,
                topK: 55,
                topP: 0.88,
                gptCondLen: 20,
                gptCondChunkLen: 6,
                maxRefLen: 24,
                soundNormRefs: false,
            },
        },
    ];
    readonly cleanPreviewPresetsByLanguage: Record<string, string[]> = {
        ru: [
            'Приветик~ Я уже ждала тебя.',
            'Я рядом.',
            'Как ты?',
            'Скучала по тебе.',
            'Сегодня у меня хорошее настроение.',
        ],
        en: [
            'Hi there. I have been waiting for you.',
            'I am right here.',
            'How are you?',
            'I missed you.',
            'I am in a good mood today.',
        ],
    };
    readonly previewPhrasesByLanguage: Record<string, string[]> = {
        ru: [
            'Приветик~ Я уже ждала тебя.',
            'Я рядом.',
            'Как ты?',
            'Скучала по тебе.',
            'Сегодня у меня хорошее настроение.',
        ],
        en: [
            'Hi there. I have been waiting for you.',
            'I am right here.',
            'How are you?',
            'I missed you.',
            'I am in a good mood today.',
        ],
    };
    readonly localizedPreviewPhrasesByLanguage: Record<string, string[]> = {
        ru: [
            'Приветик~ Я уже ждала тебя.',
            'Я рядом.',
            'Как ты?',
            'Скучала по тебе.',
            'Сегодня у меня хорошее настроение.',
        ],
        en: [
            'Hi there. I have been waiting for you.',
            'I am right here.',
            'How are you?',
            'I missed you.',
            'I am in a good mood today.',
        ],
    };
    voiceForm: FormGroup;
    originalConfig: any = {};
    previewText = 'Приветик~ Я уже ждала тебя.';
    isGeneratingPreview = false;
    isImportingVoice = false;
    isImportingRvcModel = false;
    devicesRefreshing = false;
    lastImportedVoice: ImportVoiceResponse | null = null;

    private previewAudio: HTMLAudioElement | null = null;
    private previewUrl: string | null = null;
    private sampleAudio: HTMLAudioElement | null = null;
    private sampleVoicePath: string | null = null;
    private xttsPollHandle: ReturnType<typeof setInterval> | null = null;
    private providerStatusPollHandle: ReturnType<typeof setInterval> | null = null;
    private voiceAutoApplyTimer: ReturnType<typeof setTimeout> | null = null;
    private isHydratingForm = false;
    private xttsDownloadInFlight = new Set<string>();
    currentPreviewQuickLines: string[] = [];
    providerStatus: VoiceProvidersResponse['providers']['coqui'] | null = null;
    providerStatuses: Record<string, TTSProviderStatus> = {};
    voiceModules: VoiceModuleOption[] = this.baseVoiceModules.map((module) => ({ ...module }));
    voiceModuleOptions: UiSelectOption<string>[] = this.voiceModules.map((module) => ({
        value: module.value,
        label: module.label,
        disabled: module.disabled,
    }));
    edgeVoices: { name: string; language: string; gender: string; styles: string[] }[] = [];
    edgeVoiceSearch = '';

    readonly previewQuickLines: string[] = [
        'Приветик~',
        'Я рядом.',
        'Как ты?',
        'Скучала по тебе.',
        'Сегодня у меня хорошее настроение.',
    ];

    devices$: Observable<AudioDevicesData> = new Observable<AudioDevicesData>();
    audioOutputOptions: UiSelectOption<number>[] = [];
    windowsOutputOptions: UiSelectOption<number>[] = [];
    isLoading$ = new BehaviorSubject<boolean>(true);
    localVoiceFiles: LocalVoiceFileOption[] = [];
    localXttsModels: LocalXttsModelOption[] = [];
    localRvcModels: LocalRvcModelOption[] = [];

    @ViewChild('voiceImportInput') private voiceImportInputRef?: ElementRef<HTMLInputElement>;
    @ViewChild('rvcImportInput') private rvcImportInputRef?: ElementRef<HTMLInputElement>;

    constructor(
        private fb: FormBuilder,
        private configService: ConfigService,
        private resourcesService: ResourcesService,
        private voiceService: VoiceService,
        private notificationService: NotificationService,
        private localizationService: LocalizationService,
        private cdr: ChangeDetectorRef,
    ) {
        this.voiceForm = this.createForm();
    }

    ngOnInit(): void {
        this.syncPreviewPresets(true);
        this.loadAllData();
        this.localizationService.init();
        this.voiceForm.get('activeModule')?.valueChanges.subscribe((moduleName: string) => {
            this.loadProviderResources(String(moduleName || 'coqui'));
        });
        this.getCoquiField('language')?.valueChanges.subscribe(() => this.syncPreviewPresets());
        this.getCoquiField('preloadModel')?.valueChanges.subscribe(() => this.syncProviderStatusPolling());
        this.getCoquiField('volume')?.valueChanges.subscribe(() => this.syncLocalAudioVolumes());
        this.getCoquiField('speakerWav')?.valueChanges.subscribe(() => this.scheduleCriticalVoiceAutoApply());
        this.getCoquiField('modelRevision')?.valueChanges.subscribe(() => this.scheduleCriticalVoiceAutoApply());
        this.getCoquiField('voiceSimilarity')?.valueChanges.subscribe(() => this.applyVoiceMatchingMacros());
        this.getCoquiField('referenceWeight')?.valueChanges.subscribe(() => this.applyVoiceMatchingMacros());
    }

    ngOnDestroy(): void {
        this.stopPreview();
        this.stopVoiceSample();
        this.stopXttsPolling();
        this.stopProviderStatusPolling();
        if (this.voiceAutoApplyTimer !== null) {
            clearTimeout(this.voiceAutoApplyTimer);
            this.voiceAutoApplyTimer = null;
        }
        if (this.previewUrl) {
            URL.revokeObjectURL(this.previewUrl);
            this.previewUrl = null;
        }
    }

    private createForm(): FormGroup {
        return this.fb.group({
            enabled: [false],
            activeModule: ['coqui'],
            streamingTts: [false],
            enableFallback: [true],
            useRvc: [true],
            useWindowsOutput: [true],
            outputId: [25],
            windowsOutputId: [12],
            voiceModules: this.fb.group({
                elevenlabs: this.fb.group({
                    apiKey: [''],
                    voiceId: [''],
                    modelId: [''],
                    stability: [0.5],
                    similarity: [0.75],
                }),
                edge: this.fb.group({
                    voiceLanguage: [''],
                }),
                gtts: this.fb.group({
                    language: ['ru'],
                    tld: ['com'],
                    slow: [false],
                    fallbackVoice: [''],
                }),
                offline: this.fb.group({
                    voice: [''],
                }),
                coqui: this.fb.group({
                    modelName: [this.xttsModelRoot],
                    modelRevision: [this.defaultCoquiModelRevision()],
                    speaker: [''],
                    speakerWav: [''],
                    language: ['ru'],
                    device: ['cpu'],
                    speed: [1],
                    volume: [1],
                    voiceSimilarity: [0.85],
                    referenceWeight: [0.85],
                    enableSentenceSplitting: [true],
                    streamingPrefetchChunks: [3],
                    streamingPrefetchDelayMs: [0],
                    temperature: [0.3],
                    lengthPenalty: [1],
                    repetitionPenalty: [2],
                    topK: [50],
                    topP: [0.85],
                    gptCondLen: [20],
                    gptCondChunkLen: [6],
                    maxRefLen: [30],
                    soundNormRefs: [false],
                    skipCodeBlocks: [false],
                    skipTaggedBlocks: [false],
                    onlyQuotedSpeech: [false],
                    skipAsteriskText: [true],
                    regexFilterEnabled: [false],
                    regexFilterPattern: [''],
                    lowRamMode: [false],
                    useDeepSpeed: [false],
                    preloadModel: [false],
                    keepModelLoaded: [true],
                    rvc: this.fb.group({
                        enabled: [false],
                        modelFile: [''],
                        pitch: [0],
                        filterRadius: [3],
                        rmsMixRate: [1],
                        protect: [0.5],
                        f0Method: ['fcpe'],
                        splitAudio: [true],
                        autotune: [false],
                        embedderModel: ['hubert'],
                    }),
                }),
                qwen: this.fb.group({
                    modelName: ['Qwen/Qwen3-TTS-Flash'],
                    device: ['cuda'],
                    dtype: ['bfloat16'],
                    maxSeqLen: [2048],
                    language: ['English'],
                    temperature: [0.9],
                    topK: [50],
                    repetitionPenalty: [1.05],
                    maxNewTokens: [2048],
                    doSample: [true],
                }),
            }),
        });
    }

    loadAllData(): void {
        this.isLoading$.next(true);

        forkJoin({
            config: this.configService.getConfig$().pipe(take(1)),
            devices: this.resourcesService.getAudioDevices$().pipe(take(1)),
            providers: this.voiceService.providersStatus$().pipe(take(1)),
        }).pipe(
            finalize(() => this.isLoading$.next(false))
        ).subscribe({
            next: ({ config, devices, providers }) => {
                this.loadConfig(config);
                this.loadDevices(devices);
                this.applyProviderStatuses(providers);
                this.loadProviderStatus(providers);
                this.loadProviderResources(this.getActiveModule());
                this.cdr.markForCheck();
            },
            error: (error) => {
                console.error('Error loading voice settings:', error);
                this.cdr.markForCheck();
            }
        });
    }

    private loadProviderResources(activeModule: string): void {
        const moduleName = String(activeModule || 'coqui').trim().toLowerCase();
        if (moduleName === 'edge') {
            this.resourcesService.getEdgeVoices$().pipe(take(1)).subscribe({
                next: (voices) => this.loadEdgeVoices(voices),
                error: (error) => console.error('Error loading Edge voices:', error),
            });
            return;
        }

        if (moduleName === 'coqui') {
            forkJoin({
                localVoiceFiles: this.resourcesService.getLocalVoiceFiles$().pipe(take(1)),
                localXttsModels: this.resourcesService.getLocalXttsModels$().pipe(take(1)),
                localRvcModels: this.resourcesService.getLocalRvcModels$().pipe(take(1)),
            }).subscribe({
                next: ({ localVoiceFiles, localXttsModels, localRvcModels }) => {
                    this.loadLocalVoiceFiles(localVoiceFiles);
                    this.loadLocalXttsModels(localXttsModels);
                    this.loadLocalRvcModels(localRvcModels);
                    this.reconcileSelectedModelRevision();
                    this.reconcileSelectedVoiceFile();
                    this.reconcileSelectedRvcModel();
                    this.cdr.markForCheck();
                },
                error: (error) => {
                    console.error('Error loading XTTS resources:', error);
                    this.cdr.markForCheck();
                },
            });
        }
    }

    loadConfig(config: any): void {
        if (!config?.voice) {
            return;
        }

        const voiceModules = config.voice.voiceModules || {};
        const coqui = voiceModules.coqui || {};
        const rvc = coqui.rvc || {};
        const elevenlabs = voiceModules.elevenlabs || {};
        const edge = voiceModules.edge || {};
        const gtts = voiceModules.gtts || {};
        const offline = voiceModules.offline || {};
        const qwen = voiceModules.qwen || {};
        const normalizedActiveModule = String(config.voice.activeModule || 'coqui').trim().toLowerCase();
        const activeModule = this.baseVoiceModules.some((module) => module.value === normalizedActiveModule)
            ? normalizedActiveModule
            : 'coqui';

        const formValue = {
            enabled: config.voice.enabled ?? false,
            activeModule,
            streamingTts: config.voice.streamingTts ?? false,
            enableFallback: config.voice.enableFallback ?? true,
            useRvc: config.voice.useRvc ?? true,
            useWindowsOutput: config.voice.useWindowsOutput ?? true,
            outputId: config.voice.outputId ?? 25,
            windowsOutputId: config.voice.windowsOutputId ?? 12,
            voiceModules: {
                elevenlabs: {
                    apiKey: elevenlabs.apiKey || '',
                    voiceId: elevenlabs.voiceId || '',
                    modelId: elevenlabs.modelId || '',
                    stability: elevenlabs.stability ?? 0.5,
                    similarity: elevenlabs.similarity ?? 0.75,
                },
                edge: {
                    voiceLanguage: edge.voiceLanguage || config.voice.voiceLanguage || 'ru-RU-SvetlanaNeural',
                },
                gtts: {
                    language: gtts.language || 'ru',
                    tld: gtts.tld || 'com',
                    slow: gtts.slow ?? false,
                    fallbackVoice: gtts.fallbackVoice || '',
                },
                offline: {
                    voice: offline.voice || '',
                },
                coqui: {
                    modelName: this.normalizeCoquiModelName(coqui.modelName),
                    modelRevision: this.normalizeCoquiModelRevision(coqui.modelRevision),
                    speaker: '',
                    speakerWav: this.normalizeCoquiVoiceFile(coqui.speakerWav, coqui.speaker),
                    language: coqui.language || 'ru',
                    device: coqui.device || 'cpu',
                    speed: coqui.speed ?? 1,
                    volume: coqui.volume ?? 1,
                    voiceSimilarity: coqui.voiceSimilarity ?? 0.85,
                    referenceWeight: coqui.referenceWeight ?? 0.85,
                    enableSentenceSplitting: coqui.enableSentenceSplitting ?? true,
                    streamingPrefetchChunks: coqui.streamingPrefetchChunks ?? 3,
                    streamingPrefetchDelayMs: coqui.streamingPrefetchDelayMs ?? 0,
                    temperature: coqui.temperature ?? 0.3,
                    lengthPenalty: coqui.lengthPenalty ?? 1,
                    repetitionPenalty: coqui.repetitionPenalty ?? 2,
                    topK: coqui.topK ?? 50,
                    topP: coqui.topP ?? 0.85,
                    gptCondLen: coqui.gptCondLen ?? 20,
                    gptCondChunkLen: coqui.gptCondChunkLen ?? 6,
                    maxRefLen: coqui.maxRefLen ?? 30,
                    soundNormRefs: coqui.soundNormRefs ?? false,
                    skipCodeBlocks: coqui.skipCodeBlocks ?? false,
                    skipTaggedBlocks: coqui.skipTaggedBlocks ?? false,
                    onlyQuotedSpeech: coqui.onlyQuotedSpeech ?? false,
                    skipAsteriskText: coqui.skipAsteriskText ?? true,
                    regexFilterEnabled: coqui.regexFilterEnabled ?? false,
                    regexFilterPattern: coqui.regexFilterPattern ?? '',
                    lowRamMode: coqui.lowRamMode ?? false,
                    useDeepSpeed: coqui.useDeepSpeed ?? false,
                    preloadModel: coqui.preloadModel ?? false,
                    keepModelLoaded: coqui.keepModelLoaded ?? true,
                    rvc: {
                        enabled: rvc.enabled ?? false,
                        modelFile: this.normalizeRvcModelFile(rvc.modelFile),
                        pitch: rvc.pitch ?? 0,
                        filterRadius: rvc.filterRadius ?? 3,
                        rmsMixRate: rvc.rmsMixRate ?? 1,
                        protect: rvc.protect ?? 0.5,
                        f0Method: rvc.f0Method || 'fcpe',
                        splitAudio: rvc.splitAudio ?? true,
                        autotune: rvc.autotune ?? false,
                        embedderModel: rvc.embedderModel || 'hubert',
                    },
                },
                qwen: {
                    modelName: qwen.modelName || qwen.model_name || 'Qwen/Qwen3-TTS-Flash',
                    device: qwen.device || 'cuda',
                    dtype: qwen.dtype || 'bfloat16',
                    maxSeqLen: qwen.maxSeqLen ?? qwen.max_seq_len ?? 2048,
                    language: qwen.language || 'English',
                    temperature: qwen.temperature ?? 0.9,
                    topK: qwen.topK ?? qwen.top_k ?? 50,
                    repetitionPenalty: qwen.repetitionPenalty ?? qwen.repetition_penalty ?? 1.05,
                    maxNewTokens: qwen.maxNewTokens ?? qwen.max_new_tokens ?? 2048,
                    doSample: qwen.doSample ?? qwen.do_sample ?? true,
                }
            }
        };

        this.isHydratingForm = true;
        this.voiceForm.patchValue(formValue);
        this.syncPreviewPresets(true);
        this.isHydratingForm = false;
        this.originalConfig = JSON.parse(JSON.stringify(this.voiceForm.value));
        this.cdr.markForCheck();
    }

    private scheduleCriticalVoiceAutoApply(): void {
        if (this.isHydratingForm) {
            return;
        }

        if (this.voiceAutoApplyTimer !== null) {
            clearTimeout(this.voiceAutoApplyTimer);
        }

        this.voiceAutoApplyTimer = setTimeout(() => {
            this.voiceAutoApplyTimer = null;
            this.applyVoiceChangesSilently();
        }, 420);
    }

    private applyVoiceChangesSilently(): void {
        if (this.isActiveModule('coqui')) {
            const selectedModel = this.getSelectedXttsModel();
            if (selectedModel && !selectedModel.custom && !selectedModel.installed) {
                return;
            }
        }

        const changes = this.getChanges();
        if (Object.keys(changes).length === 0) {
            return;
        }

        const voiceModel: any = {};
        for (const key of ['enabled', 'activeModule', 'streamingTts', 'enableFallback', 'useRvc', 'useWindowsOutput', 'outputId', 'windowsOutputId']) {
            if (Object.prototype.hasOwnProperty.call(changes, key)) {
                voiceModel[key] = changes[key];
            }
        }
        voiceModel.voiceModules = this.voiceForm.get('voiceModules')?.value;

        this.configService.updateConfig$({ voice: voiceModel }).pipe(take(1)).subscribe({
            next: () => {
                this.originalConfig = JSON.parse(JSON.stringify(this.voiceForm.value));
            },
            error: (error) => {
                console.error('Silent voice auto-apply failed:', error);
            },
        });
    }

    loadDevices(devices: any): void {
        const audioOutputs: AudioDevice[] = [{ id: 0, name: 'Default Device' }];
        const windowsOutputs: AudioDevice[] = [{ id: 0, name: 'Default Device' }];

        if (devices?.all_devices?.length) {
            for (const device of devices.all_devices) {
                if (device && device.length >= 2) {
                    audioOutputs.push({ id: device[0], name: device[1] });
                }
            }
        }

        if (devices?.get_windows_output?.length) {
            for (const device of devices.get_windows_output) {
                if (device && device.length >= 2) {
                    windowsOutputs.push({ id: device[0], name: device[1] });
                }
            }
        }

        this.devices$ = of({ audioOutputs, windowsOutputs });
        this.audioOutputOptions = audioOutputs.map((device) => ({
            value: device.id,
            label: `[${device.id}]: ${device.name}`,
        }));
        this.windowsOutputOptions = windowsOutputs.map((device) => ({
            value: device.id,
            label: `[${device.id}]: ${device.name}`,
        }));
        this.cdr.markForCheck();
    }

    loadLocalVoiceFiles(payload: any): void {
        if (payload?.status === 'success' && Array.isArray(payload.files)) {
            this.localVoiceFiles = payload.files;
            this.reconcileSelectedVoiceFile();
            this.cdr.markForCheck();
            return;
        }
        this.localVoiceFiles = [];
        this.reconcileSelectedVoiceFile();
        this.cdr.markForCheck();
    }

    loadLocalXttsModels(payload: any): void {
        if (payload?.status === 'success' && Array.isArray(payload.models)) {
            this.localXttsModels = payload.models;
            this.reconcileSelectedModelRevision();
            this.syncXttsPolling();
            this.cdr.markForCheck();
            return;
        }
        this.localXttsModels = [];
        this.reconcileSelectedModelRevision();
        this.syncXttsPolling();
        this.cdr.markForCheck();
    }

    loadLocalRvcModels(payload: any): void {
        if (payload?.status === 'success' && Array.isArray(payload.models)) {
            this.localRvcModels = payload.models;
            this.reconcileSelectedRvcModel();
            this.cdr.markForCheck();
            return;
        }
        this.localRvcModels = [];
        this.reconcileSelectedRvcModel();
        this.cdr.markForCheck();
    }

    get localXttsModelOptions(): UiSelectOption<string>[] {
        return this.localXttsModels.map((model) => ({
            value: model.path,
            label: model.name,
        }));
    }

    get localVoiceFileOptions(): UiSelectOption<string>[] {
        const voiceFiles = [...this.localVoiceFiles].sort((left, right) => {
            const leftReady = left.summary?.is_xtts_compatible || left.summary?.is_prepared_xtts;
            const rightReady = right.summary?.is_xtts_compatible || right.summary?.is_prepared_xtts;
            if (leftReady !== rightReady) {
                return leftReady ? -1 : 1;
            }
            return left.name.localeCompare(right.name);
        });
        const options = [
            { value: '', label: 'Not selected' },
            ...voiceFiles.map((voiceFile) => ({
                value: voiceFile.path,
                label: `${voiceFile.summary?.is_xtts_compatible || voiceFile.summary?.is_prepared_xtts ? '[XTTS]' : '[Source]'} ${voiceFile.name}`,
            })),
        ];
        const current = String(this.getCoquiField('speakerWav')?.value || '').trim();
        if (current && !options.some((item) => item.value === current)) {
            options.splice(1, 0, { value: current, label: `[Selected] ${current}` });
        }
        return options;
    }

    get localRvcModelOptions(): UiSelectOption<string>[] {
        return [
            { value: '', label: 'Not selected' },
            ...this.localRvcModels.map((model) => ({
                value: model.path,
                label: model.name,
            })),
        ];
    }

    get edgeVoiceOptions(): UiSelectOption<string>[] {
        if (!Array.isArray(this.edgeVoices) || this.edgeVoices.length === 0) {
            return [{ value: '', label: 'No voices loaded' }];
        }
        const query = this.edgeVoiceSearch.trim().toLowerCase();
        return this.edgeVoices.filter((voice) => {
            if (!query) {
                return true;
            }
            return [voice.name, voice.language, voice.gender, ...(voice.styles || [])]
                .join(' ')
                .toLowerCase()
                .includes(query);
        }).map((voice) => ({
            value: voice.name,
            label: voice.name,
        }));
    }

    loadProviderStatus(payload: VoiceProvidersResponse | null | undefined): void {
        this.providerStatus = payload?.providers?.coqui || null;
        this.syncProviderStatusPolling();
        this.cdr.markForCheck();
    }

    private loadEdgeVoices(payload: any): void {
        if (payload && payload.status === 'success' && Array.isArray(payload.voices)) {
            this.edgeVoices = payload.voices;
            this.cdr.markForCheck();
            return;
        }
        this.edgeVoices = [];
        this.cdr.markForCheck();
    }

    private syncVoiceModuleOptions(): void {
        this.voiceModuleOptions = this.voiceModules.map((module) => ({
            value: module.value,
            label: this.getModuleLabel(module),
            disabled: module.disabled,
        }));
    }

    private applyProviderStatuses(payload: any): void {
        const providers = (payload && payload.providers) || {};
        const statuses: Record<string, TTSProviderStatus> = {};

        Object.keys(providers).forEach((key) => {
            const item = providers[key] || {};
            statuses[key] = {
                available: !!item.available,
                disabled: !!item.disabled,
                cooldown: typeof item.cooldown === 'number' ? item.cooldown : 0,
                lastFailureAt: item.last_failure_at ?? null,
                lastError: item.last_error ?? null,
            };
        });

        this.providerStatuses = statuses;
        this.voiceModules = this.baseVoiceModules.map((module) => {
            const status = statuses[module.value];
            if (!status) {
                return { ...module };
            }

            const tooltipLines: string[] = [];
            if (!status.available) {
                tooltipLines.push('Provider unavailable');
            }
            if (status.disabled) {
                tooltipLines.push(`Provider disabled (cooldown ${status.cooldown.toFixed(1)}s)`);
            }
            if (status.lastError) {
                tooltipLines.push(status.lastError);
            }

            return {
                ...module,
                // Keep provider selectable in UI even when backend marks it unavailable:
                // user still needs to open the section and fill credentials/config.
                available: status.available && !status.disabled,
                disabled: false,
                tooltip: tooltipLines.length > 0 ? tooltipLines.join('\n') : undefined,
            };
        });

        this.syncVoiceModuleOptions();
        this.cdr.markForCheck();
    }

    refreshLocalVoiceFiles(): void {
        this.resourcesService.getLocalVoiceFiles$().pipe(take(1)).subscribe({
            next: (payload) => {
                this.loadLocalVoiceFiles(payload);
                const currentValue = this.getSelectedVoiceFilePath();
                if (currentValue && !this.localVoiceFiles.some((item) => item.path === currentValue)) {
                    this.stopVoiceSample();
                    this.getCoquiField('speakerWav')?.setValue('', { emitEvent: false });
                }
                this.cdr.markForCheck();
            },
            error: (error) => {
                console.error('Error refreshing local voice files:', error);
                this.cdr.markForCheck();
            },
        });
    }

    refreshLocalXttsModels(): void {
        this.resourcesService.getLocalXttsModels$().pipe(take(1)).subscribe({
            next: (payload) => {
                this.loadLocalXttsModels(payload);
                const currentValue = String(this.getCoquiField('modelRevision')?.value || '').trim();
                if (currentValue && !this.localXttsModels.some((item) => item.path === currentValue)) {
                    this.getCoquiField('modelRevision')?.setValue(this.defaultCoquiModelRevision(), { emitEvent: false });
                }
            },
            error: (error) => console.error('Error refreshing local XTTS models:', error),
        });
    }

    refreshLocalRvcModels(): void {
        this.resourcesService.getLocalRvcModels$().pipe(take(1)).subscribe({
            next: (payload) => {
                this.loadLocalRvcModels(payload);
                const currentValue = String(this.getRvcField('modelFile')?.value || '').trim();
                if (currentValue && !this.localRvcModels.some((item) => item.path === currentValue)) {
                    this.getRvcField('modelFile')?.setValue('', { emitEvent: false });
                }
            },
            error: (error) => console.error('Error refreshing local RVC models:', error),
        });
    }

    refreshDevices(): void {
        this.devicesRefreshing = true;
        this.resourcesService.getAudioDevices$().pipe(
            finalize(() => {
                this.devicesRefreshing = false;
            })
        ).subscribe((devices) => {
            this.loadDevices(devices);
        });
    }

    saveChanges(): void {
        if (this.isActiveModule('coqui')) {
            this.getCoquiField('modelName')?.setValue(this.xttsModelRoot, { emitEvent: false });
            this.getCoquiField('speaker')?.setValue('', { emitEvent: false });

            const selectedModel = this.getSelectedXttsModel();
            if (selectedModel && !selectedModel.custom && !selectedModel.installed) {
                this.notificationService.open({
                    title: 'XTTS model is not downloaded',
                    type: 'error',
                    message: `Download ${selectedModel.name} first, then apply it.`,
                    autoClose: true,
                });
                return;
            }
        }

        const changes = this.getChanges();
        if (Object.keys(changes).length === 0) {
            return;
        }

        const voiceModel: any = {};
        for (const key of ['enabled', 'activeModule', 'streamingTts', 'enableFallback', 'useRvc', 'useWindowsOutput', 'outputId', 'windowsOutputId']) {
            if (Object.prototype.hasOwnProperty.call(changes, key)) {
                voiceModel[key] = changes[key];
            }
        }

        voiceModel.voiceModules = this.voiceForm.get('voiceModules')?.value;

        this.configService.updateConfig$({ voice: voiceModel }).subscribe({
            next: (response) => {
                this.notificationService.open({
                    title: 'Voice settings updated',
                    type: 'success',
                    message: this.buildVoiceSettingsUpdatedMessage(response),
                    autoClose: true,
                });
                this.originalConfig = JSON.parse(JSON.stringify(this.voiceForm.value));
                this.refreshProviderStatus();
            },
            error: (error) => {
                this.notificationService.open({
                    title: 'Error updating voice settings',
                    type: 'error',
                    message: this.extractNotificationErrorMessage(error, 'Failed to update voice settings'),
                    autoClose: true,
                });
            }
        });
    }

    private buildVoiceSettingsUpdatedMessage(response: any): string {
        const updated = Array.isArray(response?.updated) ? response.updated.length : 0;
        if (updated > 0) {
            return `${updated} setting${updated === 1 ? '' : 's'} applied.`;
        }
        if (response?.status === 'ok') {
            return 'Changes saved.';
        }
        return 'Voice configuration saved.';
    }

    private extractNotificationErrorMessage(error: any, fallback: string): string {
        const candidates = [
            error?.error?.detail,
            error?.error?.message,
            error?.message,
            error?.statusText,
        ];
        for (const candidate of candidates) {
            if (typeof candidate === 'string' && candidate.trim()) {
                return candidate.trim();
            }
        }
        return fallback;
    }

    private getChanges(): any {
        const current = this.voiceForm.value;
        const changes: any = {};

        for (const key of Object.keys(current)) {
            const currentValue = current[key];
            const originalValue = this.originalConfig ? this.originalConfig[key] : undefined;
            const valuesDiffer = originalValue === undefined
                ? currentValue !== undefined && currentValue !== null && currentValue !== ''
                : JSON.stringify(currentValue) !== JSON.stringify(originalValue);

            if (valuesDiffer) {
                changes[key] = currentValue;
            }
        }

        return changes;
    }

    hasChanges(): boolean {
        return Object.keys(this.getChanges()).length > 0;
    }

    resetToDefaults(): void {
        this.voiceForm.reset({
            enabled: false,
            activeModule: 'coqui',
            streamingTts: false,
            enableFallback: true,
            useRvc: true,
            useWindowsOutput: true,
            outputId: 25,
            windowsOutputId: 12,
            voiceModules: {
                elevenlabs: {
                    apiKey: '',
                    voiceId: '',
                    modelId: '',
                    stability: 0.5,
                    similarity: 0.75,
                },
                edge: {
                    voiceLanguage: 'ru-RU-SvetlanaNeural',
                },
                gtts: {
                    language: 'ru',
                    tld: 'com',
                    slow: false,
                    fallbackVoice: '',
                },
                offline: {
                    voice: '',
                },
                coqui: {
                    modelName: this.xttsModelRoot,
                    modelRevision: this.defaultCoquiModelRevision(),
                    speaker: '',
                    speakerWav: '',
                    language: 'ru',
                    device: 'cpu',
                    speed: 1,
                    volume: 1,
                    voiceSimilarity: 0.85,
                    referenceWeight: 0.85,
                    enableSentenceSplitting: true,
                    streamingPrefetchChunks: 3,
                    streamingPrefetchDelayMs: 0,
                    temperature: 0.3,
                    lengthPenalty: 1,
                    repetitionPenalty: 2,
                    topK: 50,
                    topP: 0.85,
                    gptCondLen: 20,
                    gptCondChunkLen: 6,
                    maxRefLen: 30,
                    soundNormRefs: false,
                    skipCodeBlocks: false,
                    skipTaggedBlocks: false,
                    onlyQuotedSpeech: false,
                    skipAsteriskText: true,
                    regexFilterEnabled: false,
                    regexFilterPattern: '',
                    lowRamMode: false,
                    useDeepSpeed: false,
                    preloadModel: false,
                    keepModelLoaded: true,
                    rvc: {
                        enabled: false,
                        modelFile: '',
                        pitch: 0,
                        filterRadius: 3,
                        rmsMixRate: 1,
                        protect: 0.5,
                        f0Method: 'fcpe',
                        splitAudio: true,
                        autotune: false,
                        embedderModel: 'hubert',
                    },
                }
            }
        });
        this.applyVoiceMatchingMacros();
        this.syncPreviewPresets(true);
    }

    downloadSelectedXttsModel(): void {
        const selectedModel = this.getSelectedXttsModel();
        if (!selectedModel || !selectedModel.downloadable || selectedModel.downloading || this.xttsDownloadInFlight.has(selectedModel.path)) {
            return;
        }

        this.xttsDownloadInFlight.add(selectedModel.path);
        selectedModel.downloading = true;
        selectedModel.status = 'downloading';
        selectedModel.message = 'Starting download...';
        selectedModel.progress = 0;
        this.localXttsModels = [...this.localXttsModels];
        this.startXttsPolling();

        this.voiceService.downloadXttsModel$(selectedModel.path).pipe(
            take(1),
            finalize(() => {
                this.xttsDownloadInFlight.delete(selectedModel.path);
            })
        ).subscribe({
            next: () => this.refreshLocalXttsModels(),
            error: (error) => {
                const message = error?.error?.detail || 'Failed to start XTTS model download';
                this.notificationService.open({
                    title: 'XTTS download error',
                    type: 'error',
                    message,
                    autoClose: true,
                });
                this.refreshLocalXttsModels();
            }
        });
    }

    applySelectedXttsModel(): void {
        this.saveChanges();
    }

    getSelectedXttsModel(): LocalXttsModelOption | null {
        const selectedPath = String(this.getCoquiField('modelRevision')?.value || '').trim();
        return this.localXttsModels.find((item) => item.path === selectedPath) || null;
    }

    canDownloadSelectedXttsModel(): boolean {
        const selectedModel = this.getSelectedXttsModel();
        return !!selectedModel
            && selectedModel.downloadable
            && !selectedModel.installed
            && !selectedModel.downloading
            && !this.xttsDownloadInFlight.has(selectedModel.path);
    }

    canApplySelectedXttsModel(): boolean {
        const selectedModel = this.getSelectedXttsModel();
        return !!selectedModel && !selectedModel.downloading && (selectedModel.installed || selectedModel.custom);
    }

    getSelectedXttsModelProgress(): string | null {
        const selectedModel = this.getSelectedXttsModel();
        if (!selectedModel) {
            return null;
        }
        if (selectedModel.downloading) {
            const progress = this.getSelectedXttsModelProgressValue().toFixed(1);
            return selectedModel.message ? `${selectedModel.message} (${progress}%)` : `Downloading ${progress}%`;
        }
        if (selectedModel.installed) {
            return 'Installed';
        }
        if (selectedModel.custom) {
            return 'Manual folder';
        }
        return 'Not downloaded';
    }

    getSelectedXttsModelProgressValue(): number {
        const selectedModel = this.getSelectedXttsModel();
        if (!selectedModel) {
            return 0;
        }
        return Math.max(0, Math.min(100, Number(selectedModel.progress || 0)));
    }

    isSelectedXttsModelDownloading(): boolean {
        return !!this.getSelectedXttsModel()?.downloading;
    }

    private syncXttsPolling(): void {
        if (this.localXttsModels.some((item) => item.downloading || item.status === 'downloading')) {
            this.startXttsPolling();
            return;
        }
        this.stopXttsPolling();
    }

    private startXttsPolling(): void {
        if (this.xttsPollHandle !== null) {
            return;
        }
        this.xttsPollHandle = setInterval(() => this.refreshLocalXttsModels(), 600);
    }

    private stopXttsPolling(): void {
        if (this.xttsPollHandle === null) {
            return;
        }
        clearInterval(this.xttsPollHandle);
        this.xttsPollHandle = null;
    }

    private syncProviderStatusPolling(): void {
        if (this.shouldPollProviderStatus()) {
            this.startProviderStatusPolling();
            return;
        }
        this.stopProviderStatusPolling();
    }

    private shouldPollProviderStatus(): boolean {
        const preloadEnabled = this.getCoquiField('preloadModel')?.value === true;
        if (!preloadEnabled) {
            return false;
        }

        const meta = this.providerStatus?.meta;
        if (!meta) {
            return true;
        }

        if (meta.last_init_error) {
            return false;
        }

        const rvcEnabled = this.getRvcField('enabled')?.value === true;
        const rvc = meta.rvc;
        const xttsPending = !meta.engine_loaded || meta.preload_state === 'preloading' || meta.preload_state === 'idle';
        const rvcPending = rvcEnabled && (
            !rvc?.last_error && (
            rvc?.preload_state === 'preloading'
            || rvc?.preload_state === 'idle'
            || !(rvc?.model_loaded && rvc?.embedder_loaded && rvc?.f0_method_ready)
            )
        );

        return xttsPending || rvcPending;
    }

    private refreshProviderStatus(): void {
        this.voiceService.providersStatus$().pipe(take(1)).subscribe({
            next: (payload) => {
                this.loadProviderStatus(payload);
            },
            error: () => {
                // Keep the last known state if the backend is temporarily unavailable.
            },
        });
    }

    private startProviderStatusPolling(): void {
        if (this.providerStatusPollHandle !== null) {
            return;
        }
        this.refreshProviderStatus();
        this.providerStatusPollHandle = setInterval(() => {
            this.refreshProviderStatus();
        }, 1500);
    }

    private stopProviderStatusPolling(): void {
        if (this.providerStatusPollHandle === null) {
            return;
        }
        clearInterval(this.providerStatusPollHandle);
        this.providerStatusPollHandle = null;
    }

    showWindowsOutput(): boolean {
        return this.voiceForm.get('useWindowsOutput')?.value === true;
    }

    getActiveModule(): string {
        return String(this.voiceForm.get('activeModule')?.value || 'coqui');
    }

    isActiveModule(module: string): boolean {
        return this.getActiveModule() === module;
    }

    showLegacyConnectors(): boolean {
        return this.getActiveModule() !== 'coqui';
    }

    showElevenLabsFields(): boolean {
        return this.isActiveModule('elevenlabs');
    }

    showVoiceLanguage(): boolean {
        return this.isActiveModule('edge');
    }

    showGttsFields(): boolean {
        return this.isActiveModule('gtts');
    }

    showOfflineFields(): boolean {
        return this.isActiveModule('offline');
    }

    showQwenFields(): boolean {
        return this.isActiveModule('qwen');
    }

    getCoquiField(field: string) {
        return this.voiceForm.get(`voiceModules.coqui.${field}`);
    }

    getRvcField(field: string) {
        return this.voiceForm.get(`voiceModules.coqui.rvc.${field}`);
    }

    getElevenLabsField(field: string) {
        return this.voiceForm.get(`voiceModules.elevenlabs.${field}`);
    }

    getEdgeField(field: string) {
        return this.voiceForm.get(`voiceModules.edge.${field}`);
    }

    getGttsField(field: string) {
        return this.voiceForm.get(`voiceModules.gtts.${field}`);
    }

    getOfflineField(field: string) {
        return this.voiceForm.get(`voiceModules.offline.${field}`);
    }

    isModuleAvailable(value: string): boolean {
        return this.voiceModules.find((module) => module.value === value)?.available ?? false;
    }

    getModuleLabel(module: VoiceModuleOption): string {
        if (module.available) {
            return module.label;
        }
        return `${module.label} (Unavailable)`;
    }

    getModuleTooltip(module: VoiceModuleOption): string | null {
        return module.tooltip ?? null;
    }

    getRvcNumberValue(field: string, defaultValue: number): number {
        const rawValue = this.getRvcField(field)?.value;
        const numericValue = typeof rawValue === 'number' ? rawValue : Number(rawValue);
        return Number.isFinite(numericValue) ? numericValue : defaultValue;
    }

    getCoquiDeviceSelection(): string {
        return String(this.getCoquiField('device')?.value || 'cpu').toLowerCase();
    }

    isLowRamModeEnabled(): boolean {
        return this.getCoquiField('lowRamMode')?.value === true;
    }

    getLowRamModeStateLabel(): string {
        if (!this.isLowRamModeEnabled()) {
            return 'Disabled';
        }
        if (this.getCoquiDeviceSelection() !== 'cuda') {
            return 'Needs CUDA';
        }
        return 'Active';
    }

    getLowRamModeStateClass(): string {
        const state = this.getLowRamModeStateLabel();
        if (state === 'Active') {
            return 'is-active';
        }
        if (state === 'Needs CUDA') {
            return 'is-warning';
        }
        return 'is-muted';
    }

    getLowRamModeHint(): string {
        if (!this.isLowRamModeEnabled()) {
            return 'Keeps XTTS on the GPU between generations for the fastest response.';
        }
        if (this.getCoquiDeviceSelection() !== 'cuda') {
            return 'Low RAM mode only works with CUDA. On CPU it will stay inactive.';
        }
        return 'Moves XTTS between GPU and CPU to save VRAM. This usually increases reply start latency.';
    }

    getPreloadStatusLabel(): string {
        const meta = this.providerStatus?.meta;
        if (meta?.last_init_error) {
            return 'Error';
        }
        if (meta?.engine_loaded) {
            return this.isLowRamModeEnabled() ? 'Ready (CPU)' : 'Ready (GPU)';
        }
        if (meta?.preload_state === 'preloading') {
            return 'Preloading';
        }
        if (this.getCoquiField('preloadModel')?.value !== true) {
            return 'Disabled';
        }
        return 'Idle';
    }

    getPreloadStatusClass(): string {
        const label = this.getPreloadStatusLabel();
        if (label.startsWith('Ready')) {
            return 'is-active';
        }
        if (label === 'Preloading' || label === 'Idle' || label === 'Error') {
            return 'is-warning';
        }
        return 'is-muted';
    }

    getPreloadHint(): string {
        const meta = this.providerStatus?.meta;
        if (meta?.last_init_error) {
            return `Warmup failed: ${meta.last_init_error}`;
        }
        if (meta?.preload_state === 'preloading') {
            return 'XTTS is warming up in the background after launcher startup.';
        }
        if (meta?.engine_loaded && this.isLowRamModeEnabled()) {
            return 'Low RAM mode is active: XTTS is initialized, but stored on CPU between replies to save VRAM. The first spoken line can still spend a few seconds moving back to GPU.';
        }
        if (meta?.engine_loaded) {
            return 'XTTS is already loaded and should start speaking much faster.';
        }
        if (this.getCoquiField('preloadModel')?.value === true) {
            return 'Warmup is enabled, but the model has not finished loading yet.';
        }
        return 'Enable this to warm up XTTS during launcher startup.';
    }

    private isRvcRuntimeReady(): boolean {
        const rvc = this.providerStatus?.meta?.rvc;
        return !!(rvc?.model_loaded && rvc?.embedder_loaded && rvc?.f0_method_ready);
    }

    getRvcStatusLabel(): string {
        const rvc = this.providerStatus?.meta?.rvc;
        const preloadEnabled = this.getCoquiField('preloadModel')?.value === true;
        if (this.getRvcField('enabled')?.value !== true) {
            return 'Disabled';
        }
        if (!this.getSelectedRvcModelPath()) {
            return 'No model';
        }
        if (!rvc?.base_assets_ready) {
            return 'Missing base';
        }
        if (!rvc?.embedder_ready) {
            return 'Missing embedder';
        }
        if (rvc?.last_error) {
            return preloadEnabled ? 'Error' : 'Fallback';
        }
        if (preloadEnabled && rvc?.preload_state === 'preloading') {
            return 'Preloading';
        }
        if (this.isRvcRuntimeReady()) {
            return 'Ready';
        }
        return preloadEnabled ? 'Idle' : 'On demand';
    }

    getRvcStatusClass(): string {
        const status = this.getRvcStatusLabel();
        if (status === 'Ready') {
            return 'is-active';
        }
        if (
            status === 'Fallback'
            || status === 'Error'
            || status === 'Missing base'
            || status === 'Missing embedder'
            || status === 'No model'
            || status === 'Preloading'
            || status === 'Idle'
        ) {
            return 'is-warning';
        }
        return 'is-muted';
    }

    getRvcHint(): string {
        const rvc = this.providerStatus?.meta?.rvc;
        const preloadEnabled = this.getCoquiField('preloadModel')?.value === true;
        if (rvc?.last_error) {
            return preloadEnabled ? `RVC preload failed: ${rvc.last_error}` : `RVC fallback active: ${rvc.last_error}`;
        }
        if (this.getRvcField('enabled')?.value !== true) {
            return 'XTTS audio will be sent through RVC before preview and playback when enabled.';
        }
        if (!rvc?.base_assets_ready) {
            return 'Base RVC assets are not ready yet. Put required files into backend/storage/models/rvc/rvc_base.';
        }
        if (!rvc?.embedder_ready) {
            return 'Selected embedder is missing. Put hubert_base.pt or contentvec_base.pt into backend/storage/models/rvc/embedder.';
        }
        if (!this.getSelectedRvcModelPath()) {
            return 'Choose a .pth voice model from backend/storage/models/rvc/rvc_voices.';
        }
        if (preloadEnabled && rvc?.preload_state === 'preloading') {
            return 'RVC runtime is warming up during launcher startup.';
        }
        if (this.isRvcRuntimeReady()) {
            const loadedModel = String(rvc?.loaded_model_file || this.getSelectedRvcModelName() || '').trim();
            const modelText = loadedModel ? `Loaded model: ${loadedModel}. ` : '';
            return `${modelText}Selected embedder and F0 method are ready.`;
        }
        if (!preloadEnabled) {
            return 'RVC runtime will load on the first preview or spoken reply.';
        }
        const methods = Array.isArray(rvc?.available_f0_methods) ? rvc.available_f0_methods.join(', ') : '';
        return methods ? `Available F0 methods: ${methods}.` : 'RVC dependencies are unavailable in the current runtime.';
    }

    getSelectedRvcModelPath(): string {
        return this.normalizeRvcModelFile(this.getRvcField('modelFile')?.value);
    }

    getSelectedVoiceFilePath(): string {
        return this.normalizeCoquiVoiceFile(this.getCoquiField('speakerWav')?.value);
    }

    getSelectedRvcModelName(): string {
        const selectedPath = this.getSelectedRvcModelPath();
        return this.localRvcModels.find((item) => item.path === selectedPath)?.name || '';
    }

    getSelectedVoiceFile(): LocalVoiceFileOption | null {
        const selectedPath = this.getSelectedVoiceFilePath();
        return this.localVoiceFiles.find((item) => item.path === selectedPath) || null;
    }

    getSelectedVoiceSummaryRows(): Array<{ label: string; value: string }> {
        const selectedVoice = this.getSelectedVoiceFile();
        const summary = selectedVoice?.summary;
        if (!selectedVoice || !summary) {
            return [];
        }

        const rows: Array<{ label: string; value: string }> = [];
        if (typeof summary.duration_seconds === 'number' && summary.duration_seconds > 0) {
            rows.push({ label: 'Duration', value: this.formatVoiceDuration(summary.duration_seconds) });
        }
        if (typeof summary.sample_rate === 'number' && summary.sample_rate > 0) {
            rows.push({ label: 'Sample rate', value: this.formatSampleRate(summary.sample_rate) });
        }
        if (typeof summary.channels === 'number' && summary.channels > 0) {
            rows.push({ label: 'Channels', value: this.formatChannels(summary.channels) });
        }
        if (summary.codec) {
            rows.push({ label: 'Format', value: String(summary.codec).toUpperCase() });
        }
        return rows;
    }

    getSelectedVoiceHint(): string {
        return String(this.getSelectedVoiceFile()?.summary?.hint || '').trim();
    }

    getSelectedVoiceHealthLabel(): string {
        const summary = this.getSelectedVoiceFile()?.summary;
        if (!summary) {
            return '';
        }
        if (summary.is_xtts_compatible || summary.is_prepared_xtts) {
            return 'XTTS ready';
        }
        switch (summary.health) {
            case 'short':
                return 'Short sample';
            case 'long':
                return 'Long sample';
            case 'converted_recommended':
                return 'Conversion recommended';
            case 'unknown':
                return 'Unknown';
            default:
                return 'Ready';
        }
    }

    getSelectedVoiceHealthClass(): string {
        const summary = this.getSelectedVoiceFile()?.summary;
        if (!summary) {
            return 'is-muted';
        }
        if (summary.is_xtts_compatible || summary.is_prepared_xtts) {
            return 'is-active';
        }
        if (summary.health === 'short' || summary.health === 'long' || summary.health === 'converted_recommended') {
            return 'is-warning';
        }
        return 'is-muted';
    }

    hasLastImportedVoice(): boolean {
        return !!this.lastImportedVoice;
    }

    getLastImportedVoiceRows(): Array<{ label: string; value: string }> {
        const payload = this.lastImportedVoice;
        if (!payload) {
            return [];
        }
        return [
            { label: 'Source', value: payload.original_file?.name || 'Unknown' },
            { label: 'Prepared', value: payload.processed_file?.name || 'Unknown' },
            { label: 'Duration', value: this.formatVoiceDuration(payload.processed_duration_seconds) },
            { label: 'XTTS format', value: `${this.formatSampleRate(payload.sample_rate)} / ${this.formatChannels(payload.channels)}` },
        ];
    }

    getLastImportedVoiceHint(): string {
        const hint = this.lastImportedVoice?.processed_summary?.hint;
        return String(hint || 'Prepared XTTS sample is ready to use.').trim();
    }

    canPlaySelectedVoiceSample(): boolean {
        return !!this.getSelectedVoiceFilePath();
    }

    getVoiceImportButtonLabel(): string {
        return this.isImportingVoice ? 'Importing...' : 'Import';
    }

    isSelectedVoiceSamplePlaying(): boolean {
        return !!this.sampleAudio && this.sampleVoicePath === this.getSelectedVoiceFilePath();
    }

    toggleVoiceSample(): void {
        const selectedPath = this.getSelectedVoiceFilePath();
        if (!selectedPath) {
            return;
        }

        if (this.sampleAudio && this.sampleVoicePath === selectedPath) {
            this.stopVoiceSample();
            return;
        }

        this.stopVoiceSample();
        const audio = new Audio(this.resourcesService.getLocalVoiceFileUrl(selectedPath));
        this.sampleAudio = audio;
        this.sampleVoicePath = selectedPath;
        this.syncLocalAudioVolumes();

        audio.onended = () => this.stopVoiceSample();
        audio.onerror = () => {
            this.stopVoiceSample();
            this.notificationService.open({
                title: 'Voice sample error',
                type: 'error',
                message: 'Failed to play selected voice file',
                autoClose: true,
            });
        };

        audio.play().catch((error) => {
            console.error('Voice sample playback error:', error);
            this.stopVoiceSample();
            this.notificationService.open({
                title: 'Voice sample error',
                type: 'error',
                message: 'Failed to play selected voice file',
                autoClose: true,
            });
        });
    }

    stopVoiceSample(): void {
        if (this.sampleAudio) {
            this.sampleAudio.pause();
            this.sampleAudio.currentTime = 0;
            this.sampleAudio = null;
        }
        this.sampleVoicePath = null;
    }

    openVoiceImportDialog(): void {
        if (!this.isImportingVoice) {
            this.voiceImportInputRef?.nativeElement.click();
        }
    }

    openRvcImportDialog(): void {
        if (!this.isImportingRvcModel) {
            this.rvcImportInputRef?.nativeElement.click();
        }
    }

    onVoiceImportSelected(event: Event): void {
        const input = event.target as HTMLInputElement | null;
        const file = input?.files?.[0];
        if (!file || this.isImportingVoice) {
            if (input) {
                input.value = '';
            }
            return;
        }

        this.isImportingVoice = true;
        this.voiceService.importVoice$(file).pipe(
            finalize(() => {
                this.isImportingVoice = false;
                if (input) {
                    input.value = '';
                }
            })
        ).subscribe({
            next: (payload) => this.handleImportedVoice(payload),
            error: (error) => {
                const message = error?.error?.detail || 'Failed to import voice file';
                this.notificationService.open({
                    title: 'Voice import error',
                    type: 'error',
                    message,
                    autoClose: true,
                });
            }
        });
    }

    private handleImportedVoice(payload: ImportVoiceResponse): void {
        this.lastImportedVoice = payload;
        const processedPath = String(payload?.processed_file?.path || '').trim();
        if (processedPath) {
            this.stopVoiceSample();
            this.getCoquiField('speakerWav')?.setValue(processedPath, { emitEvent: true });
        }

        this.refreshLocalVoiceFiles();
        this.notificationService.open({
            title: 'Voice imported',
            type: 'success',
            message: this.buildVoiceImportNotificationMessage(payload),
            duration: 4500,
            autoClose: true,
        });
    }

    onRvcImportSelected(event: Event): void {
        const input = event.target as HTMLInputElement | null;
        const file = input?.files?.[0];
        if (!file || this.isImportingRvcModel) {
            if (input) {
                input.value = '';
            }
            return;
        }
        this.isImportingRvcModel = true;
        this.voiceService.importRvcModel$(file).pipe(
            finalize(() => {
                this.isImportingRvcModel = false;
                if (input) {
                    input.value = '';
                }
            })
        ).subscribe({
            next: (payload) => {
                const modelPath = String(payload?.model?.path || '').trim();
                if (modelPath) {
                    this.getRvcField('modelFile')?.setValue(modelPath, { emitEvent: false });
                }
                this.refreshLocalRvcModels();
                this.notificationService.open({
                    title: 'RVC model imported',
                    type: 'success',
                    message: payload?.model?.name || 'Model imported.',
                    autoClose: true,
                });
            },
            error: (error: any) => {
                this.notificationService.open({
                    title: 'RVC import error',
                    type: 'error',
                    message: error?.error?.detail || 'Failed to import RVC model',
                    autoClose: true,
                });
            },
        });
    }

    private buildVoiceImportNotificationMessage(payload: ImportVoiceResponse): string {
        const preparedName = String(payload?.processed_file?.name || 'Prepared voice sample').trim();
        const duration = this.formatVoiceDuration(payload?.processed_duration_seconds);
        const sampleRate = this.formatSampleRate(payload?.sample_rate);
        const channels = this.formatChannels(payload?.channels);
        return `${preparedName}\n${duration} · ${sampleRate} · ${channels}`;
    }

    private formatVoiceDuration(value: unknown): string {
        const seconds = Number(value);
        if (!Number.isFinite(seconds) || seconds <= 0) {
            return 'Unknown';
        }
        if (seconds < 10) {
            return `${seconds.toFixed(2)} s`;
        }
        return `${seconds.toFixed(1)} s`;
    }

    private formatSampleRate(value: unknown): string {
        const sampleRate = Number(value);
        if (!Number.isFinite(sampleRate) || sampleRate <= 0) {
            return 'Unknown';
        }
        if (sampleRate >= 1000) {
            const khz = sampleRate / 1000;
            const formatted = Number.isInteger(khz) ? String(khz) : khz.toFixed(1);
            return `${formatted} kHz`;
        }
        return `${Math.round(sampleRate)} Hz`;
    }

    private formatChannels(value: unknown): string {
        const channels = Number(value);
        if (!Number.isFinite(channels) || channels <= 0) {
            return 'Unknown';
        }
        if (channels === 1) {
            return 'Mono';
        }
        if (channels === 2) {
            return 'Stereo';
        }
        return `${Math.round(channels)} ch`;
    }

    getCoquiSpeedLabel(): string {
        const rawValue = Number(this.getCoquiField('speed')?.value ?? 1);
        return Number.isFinite(rawValue) ? rawValue.toFixed(2).replace('.', ',') : '1,00';
    }

    getCoquiVolumeLabel(): string {
        const rawValue = Number(this.getCoquiField('volume')?.value ?? 1);
        if (!Number.isFinite(rawValue)) {
            return '100%';
        }
        return `${Math.round(rawValue * 100)}%`;
    }

    getCoquiChunkLengthLabel(): string {
        const rawValue = Number(this.getCoquiField('maxChunkLength')?.value ?? 180);
        return Number.isFinite(rawValue) ? String(Math.round(rawValue)) : '180';
    }

    getPreviewChunkDebugRows(): PreviewChunkDebugRow[] {
        return this.buildPreviewChunkDebugRows(String(this.previewText || ''));
    }

    getCoquiPauseScaleLabel(): string {
        const rawValue = Number(this.getCoquiField('chunkPauseScale')?.value ?? 1);
        return Number.isFinite(rawValue) ? rawValue.toFixed(2) : '1.00';
    }

    private buildPreviewChunkDebugRows(text: string): PreviewChunkDebugRow[] {
        const source = String(text || '').trim();
        if (!source) {
            return [];
        }

        const rows: PreviewChunkDebugRow[] = [];
        let remainder = source;
        let nextIndex = 1;

        const firstChunk = this.extractPreviewFirstChunk(remainder);
        if (firstChunk) {
            rows.push({
                index: nextIndex++,
                reason: 'first_chunk',
                length: firstChunk.length,
                text: firstChunk,
            });
            remainder = remainder.slice(firstChunk.length).replace(/^\s+/, '');
        }

        while (remainder) {
            const result = this.choosePreviewChunkSplit(remainder);
            if (!result || result.cut <= 0) {
                rows.push({
                    index: nextIndex++,
                    reason: 'tail',
                    length: remainder.length,
                    text: remainder,
                });
                break;
            }

            const chunk = this.normalizePreviewChunk(remainder.slice(0, result.cut));
            if (!chunk) {
                break;
            }

            rows.push({
                index: nextIndex++,
                reason: result.reason,
                length: chunk.length,
                text: chunk,
            });
            remainder = remainder.slice(result.cut).replace(/^\s+/, '');
        }

        return rows;
    }

    private extractPreviewFirstChunk(text: string): string | null {
        const source = String(text || '');
        if (!source.trim()) {
            return null;
        }

        const wordMatches: RegExpExecArray[] = [];
        const wordRegex = /\S+/g;
        let wordMatch: RegExpExecArray | null = null;
        while ((wordMatch = wordRegex.exec(source)) !== null) {
            wordMatches.push(wordMatch);
        }
        const minimumWords = this.getCoquiIntValue('firstChunkMinWords', 3);
        const minimumChars = this.getCoquiIntValue('firstChunkMinChars', 8);
        const preferredWords = Math.max(minimumWords, this.getCoquiIntValue('firstChunkPreferredWords', 3));
        const maximumWords = Math.max(preferredWords, this.getCoquiIntValue('firstChunkMaxWords', 8));

        if (wordMatches.length < minimumWords) {
            return null;
        }

        const effectiveMax = Math.min(wordMatches.length, maximumWords);
        let leadEnd = -1;

        for (let index = 0; index < effectiveMax; index += 1) {
            const match = wordMatches[index];
            const afterWord = match.index! + match[0].length;
            let cursor = afterWord;
            while (cursor < source.length && /\s/.test(source[cursor])) {
                cursor += 1;
            }

            const wordCount = index + 1;
            if (wordCount < minimumWords || afterWord < minimumChars) {
                continue;
            }

            if (cursor >= source.length) {
                leadEnd = afterWord;
                break;
            }

            if (source.startsWith('...', cursor) || source[cursor] === '…') {
                leadEnd = cursor + (source.startsWith('...', cursor) ? 3 : 1);
                break;
            }

            if ('.!?'.includes(source[cursor])) {
                leadEnd = cursor + 1;
                break;
            }

            if (',;:'.includes(source[cursor]) && wordCount >= minimumWords) {
                leadEnd = cursor + 1;
                break;
            }

            if (source[cursor] === '\n' && wordCount >= minimumWords) {
                leadEnd = cursor + 1;
                break;
            }

            if (wordCount >= preferredWords) {
                leadEnd = afterWord;
                break;
            }
        }

        if (leadEnd < 0) {
            return null;
        }

        return this.normalizePreviewChunk(source.slice(0, leadEnd));
    }

    private choosePreviewChunkSplit(text: string): { cut: number; reason: string } | null {
        const source = String(text || '');
        if (!source) {
            return null;
        }

        const maxChunkLength = this.getCoquiIntValue('maxChunkLength', 180);
        const minChunkSize = Math.min(maxChunkLength, this.getCoquiIntValue('minChunkSize', 90));
        const targetChunkSize = Math.min(maxChunkLength, Math.max(minChunkSize, this.getCoquiIntValue('targetChunkSize', 130)));
        const chunkSearchWindow = this.getCoquiIntValue('chunkSearchWindow', 40);
        const punctuationPriority = this.getPreviewPunctuationPriority();

        if (source.length < minChunkSize) {
            return null;
        }

        const searchEnd = Math.min(source.length, maxChunkLength);
        const searchStart = Math.max(minChunkSize, targetChunkSize - chunkSearchWindow);
        const searchWindowEnd = Math.min(searchEnd, targetChunkSize + chunkSearchWindow);

        const inWindowCut = this.findPreviewPunctuationCut(source, searchStart, searchWindowEnd, punctuationPriority);
        if (inWindowCut) {
            return inWindowCut;
        }

        if (source.length < maxChunkLength) {
            return null;
        }

        const anyPunctuationCut = this.findPreviewPunctuationCut(source, minChunkSize, searchEnd, punctuationPriority);
        if (anyPunctuationCut) {
            return anyPunctuationCut;
        }

        const whitespaceCut = this.findPreviewWhitespaceCut(source, minChunkSize, searchEnd);
        if (whitespaceCut) {
            return { cut: whitespaceCut, reason: 'forced_whitespace' };
        }

        return { cut: searchEnd, reason: 'forced_max' };
    }

    private findPreviewPunctuationCut(
        source: string,
        searchStart: number,
        searchEnd: number,
        punctuationPriority: string[],
    ): { cut: number; reason: string } | null {
        if (searchEnd <= searchStart) {
            return null;
        }

        for (const token of punctuationPriority) {
            const index = source.lastIndexOf(token, searchEnd - 1);
            if (index < searchStart || index < 0) {
                continue;
            }

            const cut = this.consumePreviewBoundarySpaces(source, index + token.length);
            return { cut, reason: `punctuation ${token}` };
        }

        return null;
    }

    private findPreviewWhitespaceCut(source: string, searchStart: number, searchEnd: number): number | null {
        for (let index = searchEnd - 1; index >= searchStart; index -= 1) {
            if (/\s/.test(source[index])) {
                return this.consumePreviewBoundarySpaces(source, index + 1);
            }
        }
        return null;
    }

    private consumePreviewBoundarySpaces(source: string, start: number): number {
        let cursor = Math.max(0, Math.min(source.length, start));
        while (cursor < source.length && /[\s]/.test(source[cursor])) {
            cursor += 1;
        }
        return cursor;
    }

    private getPreviewPunctuationPriority(): string[] {
        const rawValue = this.getCoquiField('punctuationPriority')?.value;
        if (!Array.isArray(rawValue)) {
            return ['...', '.', '!', '?', ':', ';', ',', '-'];
        }

        const normalized = rawValue
            .map((item: unknown) => String(item || '').trim())
            .filter((item: string, index: number, array: string[]) => !!item && array.indexOf(item) === index);

        return normalized.length ? normalized : ['...', '.', '!', '?', ':', ';', ',', '-'];
    }

    private normalizePreviewChunk(value: string): string {
        return String(value || '').replace(/\s+/g, ' ').trim();
    }

    getCoquiIntValue(field: string, fallback: number): number {
        const rawValue = Number(this.getCoquiField(field)?.value ?? fallback);
        if (!Number.isFinite(rawValue)) {
            return fallback;
        }
        return Math.round(rawValue);
    }

    adjustCoquiIntValue(
        field: string,
        direction: -1 | 1,
        limits: { step?: number; min: number; max: number },
    ): void {
        const control = this.getCoquiField(field);
        if (!control) {
            return;
        }

        const step = Number(limits.step ?? 1) || 1;
        const min = Number(limits.min);
        const max = Number(limits.max);
        const baseValue = this.getCoquiIntValue(field, min);
        const nextValue = Math.max(min, Math.min(max, baseValue + direction * step));
        control.setValue(nextValue);
    }

    getPrefetchChunkCards(): number[] {
        const total = this.getCoquiIntValue('streamingPrefetchChunks', 3);
        return Array.from({ length: Math.max(1, Math.min(4, total)) }, (_, index) => index + 1);
    }

    getCoquiTemperatureLabel(): string {
        const rawValue = Number(this.getCoquiField('temperature')?.value ?? 0.3);
        return Number.isFinite(rawValue) ? rawValue.toFixed(2) : '0.30';
    }

    getCoquiRepetitionPenaltyLabel(): string {
        const rawValue = Number(this.getCoquiField('repetitionPenalty')?.value ?? 2);
        return Number.isFinite(rawValue) ? rawValue.toFixed(2) : '2.00';
    }

    getCoquiTopKLabel(): string {
        const rawValue = Number(this.getCoquiField('topK')?.value ?? 50);
        return Number.isFinite(rawValue) ? String(Math.round(rawValue)) : '50';
    }

    getCoquiTopPLabel(): string {
        const rawValue = Number(this.getCoquiField('topP')?.value ?? 0.85);
        return Number.isFinite(rawValue) ? rawValue.toFixed(2) : '0.85';
    }

    getVoiceSimilarityLabel(): string {
        const rawValue = Number(this.getCoquiField('voiceSimilarity')?.value ?? 0.85);
        return Number.isFinite(rawValue) ? rawValue.toFixed(2) : '0.85';
    }

    getReferenceWeightLabel(): string {
        const rawValue = Number(this.getCoquiField('referenceWeight')?.value ?? 0.85);
        return Number.isFinite(rawValue) ? rawValue.toFixed(2) : '0.85';
    }

    getCoquiLengthPenaltyLabel(): string {
        const rawValue = Number(this.getCoquiField('lengthPenalty')?.value ?? 1);
        return Number.isFinite(rawValue) ? rawValue.toFixed(2) : '1.00';
    }

    getCoquiGptCondLenLabel(): string {
        return String(this.getCoquiIntValue('gptCondLen', 20));
    }

    getCoquiGptCondChunkLenLabel(): string {
        return String(this.getCoquiIntValue('gptCondChunkLen', 6));
    }

    getCoquiMaxRefLenLabel(): string {
        return String(this.getCoquiIntValue('maxRefLen', 30));
    }

    applyXttsVoicePreset(presetKey: string): void {
        const preset = this.xttsVoicePresets.find((item) => item.key === presetKey);
        const coquiGroup = this.voiceForm.get('voiceModules.coqui');
        if (!preset || !coquiGroup) {
            return;
        }

        coquiGroup.patchValue(preset.values, { emitEvent: false });
        this.applyVoiceChangesSilently();
    }

    getActiveXttsVoicePresetKey(): string | null {
        for (const preset of this.xttsVoicePresets) {
            if (this.isCurrentXttsVoicePreset(preset)) {
                return preset.key;
            }
        }
        return null;
    }

    isXttsVoicePresetActive(presetKey: string): boolean {
        return this.getActiveXttsVoicePresetKey() === presetKey;
    }

    private getCoquiFloatValue(field: string, fallback: number): number {
        const rawValue = Number(this.getCoquiField(field)?.value ?? fallback);
        if (!Number.isFinite(rawValue)) {
            return fallback;
        }
        return rawValue;
    }

    private clampNumber(value: number, min: number, max: number): number {
        return Math.min(max, Math.max(min, value));
    }

    private lerp(min: number, max: number, amount: number): number {
        return min + (max - min) * amount;
    }

    private roundTo(value: number, digits: number): number {
        const factor = Math.pow(10, digits);
        return Math.round(value * factor) / factor;
    }

    private isCurrentXttsVoicePreset(preset: XttsVoicePreset): boolean {
        const values = preset.values;
        return this.areNumbersClose(this.getCoquiFloatValue('voiceSimilarity', 0.85), values.voiceSimilarity)
            && this.areNumbersClose(this.getCoquiFloatValue('referenceWeight', 0.85), values.referenceWeight)
            && this.areNumbersClose(this.getCoquiFloatValue('speed', 1), values.speed)
            && this.areNumbersClose(this.getCoquiFloatValue('temperature', 0.3), values.temperature)
            && this.areNumbersClose(this.getCoquiFloatValue('lengthPenalty', 1), values.lengthPenalty)
            && this.areNumbersClose(this.getCoquiFloatValue('repetitionPenalty', 2), values.repetitionPenalty)
            && this.getCoquiIntValue('topK', 50) === values.topK
            && this.areNumbersClose(this.getCoquiFloatValue('topP', 0.85), values.topP)
            && this.getCoquiIntValue('gptCondLen', 20) === values.gptCondLen
            && this.getCoquiIntValue('gptCondChunkLen', 6) === values.gptCondChunkLen
            && this.getCoquiIntValue('maxRefLen', 30) === values.maxRefLen
            && this.getCoquiField('soundNormRefs')?.value === values.soundNormRefs;
    }

    private areNumbersClose(left: number, right: number, tolerance = 0.011): boolean {
        return Math.abs(left - right) <= tolerance;
    }

    private applyVoiceMatchingMacros(): void {
        if (this.isHydratingForm) {
            return;
        }

        const coquiGroup = this.voiceForm.get('voiceModules.coqui');
        if (!coquiGroup) {
            return;
        }

        const similarity = this.clampNumber(this.getCoquiFloatValue('voiceSimilarity', 0.85), 0, 1);
        const referenceWeight = this.clampNumber(this.getCoquiFloatValue('referenceWeight', 0.85), 0, 1);
        const matchStrength = this.clampNumber((similarity * 0.6) + (referenceWeight * 0.4), 0, 1);

        coquiGroup.patchValue({
            temperature: this.roundTo(this.lerp(0.55, 0.18, matchStrength), 2),
            lengthPenalty: 1,
            repetitionPenalty: this.roundTo(this.lerp(1.7, 2.3, matchStrength), 2),
            topK: Math.round(this.lerp(40, 60, referenceWeight)),
            topP: this.roundTo(this.lerp(0.95, 0.78, matchStrength), 2),
            gptCondLen: Math.round(this.lerp(12, 26, similarity)),
            gptCondChunkLen: 6,
            maxRefLen: Math.round(this.lerp(12, 30, referenceWeight)),
            soundNormRefs: false,
        }, { emitEvent: false });
    }

    private normalizeCoquiModelName(modelName: string | null | undefined): string {
        const value = String(modelName || '').trim();
        if (!value || value === 'tts_models/multilingual/multi-dataset/xtts_v2' || value === 'Models/xtts' || value === 'models/xtts') {
            return this.xttsModelRoot;
        }
        return value;
    }

    private normalizeCoquiModelRevision(modelRevision: string | null | undefined): string {
        const value = String(modelRevision || '').trim();
        if (!value || value === 'main') {
            return this.defaultCoquiModelRevision();
        }
        return value;
    }

    private defaultCoquiModelRevision(): string {
        const installedModel = this.localXttsModels.find((item) => item.installed && !item.custom);
        if (installedModel) {
            return installedModel.path;
        }
        const latestOfficialModel = this.localXttsModels.find((item) => item.name === 'xttsv2_2.0.3');
        if (latestOfficialModel) {
            return latestOfficialModel.path;
        }
        if (this.localXttsModels.length > 0) {
            return this.localXttsModels[0].path;
        }
        return 'xttsv2_2.0.3';
    }

    private normalizeCoquiVoiceFile(...candidates: Array<string | null | undefined>): string {
        const normalizedCandidates = candidates
            .map((candidate) => String(candidate || '').trim().replace(/\\/g, '/'))
            .filter(Boolean);
        if (this.localVoiceFiles.length === 0) {
            return normalizedCandidates[0] || '';
        }
        const availablePaths = new Set(this.localVoiceFiles.map((item) => item.path));
        const xttsReadyFiles = this.localVoiceFiles.filter(
            (item) => item.summary?.is_xtts_compatible || item.summary?.is_prepared_xtts
        );

        const findPreparedCompanion = (value: string): string => {
            const normalizedValue = String(value || '').trim().replace(/\\/g, '/');
            if (!normalizedValue) {
                return '';
            }

            const lowerValue = normalizedValue.toLowerCase();
            const stem = lowerValue.replace(/\.[^.]+$/, '');
            const normalizedStem = stem.endsWith('_xtts') ? stem.slice(0, -5) : stem;

            const preparedByPath = xttsReadyFiles.find((item) => item.path.toLowerCase() === `${normalizedStem}_xtts.wav`);
            if (preparedByPath) {
                return preparedByPath.path;
            }

            const preparedByStem = xttsReadyFiles.find((item) => {
                const itemStem = item.name.replace(/\.[^.]+$/, '').toLowerCase();
                return itemStem === `${normalizedStem}_xtts` || itemStem === normalizedStem;
            });
            return preparedByStem?.path || '';
        };

        for (const value of normalizedCandidates) {
            const preparedCompanion = findPreparedCompanion(value);
            if (preparedCompanion && availablePaths.has(preparedCompanion)) {
                return preparedCompanion;
            }
            if (availablePaths.has(value)) {
                return value;
            }
            const byName = this.localVoiceFiles.find((item) => item.name === value);
            if (byName) {
                return byName.path;
            }
            const lowerValue = value.toLowerCase();
            const byBaseName = this.localVoiceFiles.find((item) => item.name.toLowerCase() === lowerValue);
            if (byBaseName) {
                return byBaseName.path;
            }
            const byStem = this.localVoiceFiles.find((item) => item.name.replace(/\.[^.]+$/, '').toLowerCase() === lowerValue);
            if (byStem) {
                return byStem.path;
            }
        }

        return '';
    }

    private normalizeRvcModelFile(modelFile: string | null | undefined): string {
        const value = String(modelFile || '').trim().replace(/\\/g, '/');
        if (!value) {
            return '';
        }
        const exact = this.localRvcModels.find((item) => item.path === value);
        if (exact) {
            return exact.path;
        }
        const byName = this.localRvcModels.find((item) => item.name === value);
        if (byName) {
            return byName.path;
        }
        return value;
    }

    private reconcileSelectedVoiceFile(): void {
        const control = this.getCoquiField('speakerWav');
        if (!control) {
            return;
        }

        const current = String(control.value || '').trim();
        const normalized = this.normalizeCoquiVoiceFile(current);
        if (normalized !== current) {
            control.setValue(normalized, { emitEvent: false });
        }
    }

    private reconcileSelectedModelRevision(): void {
        const control = this.getCoquiField('modelRevision');
        if (!control) {
            return;
        }

        const current = String(control.value || '').trim();
        if (current && this.localXttsModels.some((item) => item.path === current)) {
            return;
        }

        const normalized = this.normalizeCoquiModelRevision(current);
        if (normalized !== current) {
            control.setValue(normalized, { emitEvent: false });
        }
    }

    private reconcileSelectedRvcModel(): void {
        const control = this.getRvcField('modelFile');
        if (!control) {
            return;
        }

        const current = String(control.value || '').trim();
        const normalized = this.normalizeRvcModelFile(current);
        if (normalized !== current) {
            control.setValue(normalized, { emitEvent: false });
        }
    }

    setPreviewText(value: string): void {
        this.previewText = value;
    }

    private getPreviewPresets(language: string): string[] {
        const normalized = String(language || 'ru').trim().toLowerCase();
        return this.cleanPreviewPresetsByLanguage[normalized] || this.cleanPreviewPresetsByLanguage.ru;
    }

    private syncPreviewPresets(forceText = false): void {
        const language = String(this.getCoquiField('language')?.value || 'ru');
        this.currentPreviewQuickLines = [...this.getPreviewPresets(language)];
        if (forceText || !String(this.previewText || '').trim()) {
            this.previewText = this.currentPreviewQuickLines[0] || '';
        }
    }

    generatePreview(): void {
        const text = (this.previewText || '').trim();
        if (!text || this.isGeneratingPreview) {
            return;
        }
        const previewValidationMessage = this.getPreviewValidationMessage();
        if (previewValidationMessage) {
            this.notificationService.open({
                title: 'Voice preview error',
                type: 'warning',
                message: previewValidationMessage,
                autoClose: true,
            });
            return;
        }

        this.stopPreview();
        this.isGeneratingPreview = true;

        this.voiceService.preview$(text, this.voiceForm.value).pipe(
            finalize(() => {
                this.isGeneratingPreview = false;
                this.cdr.markForCheck();
            })
        ).subscribe({
            next: (blob: Blob) => {
                if (this.previewUrl) {
                    URL.revokeObjectURL(this.previewUrl);
                }

                this.previewUrl = URL.createObjectURL(blob);
                this.previewAudio = new Audio(this.previewUrl);
                this.syncLocalAudioVolumes();
                this.cdr.markForCheck();
                this.previewAudio.play().catch((error) => {
                    console.error('Preview playback error:', error);
                    this.notificationService.open({
                        title: 'Voice preview error',
                        type: 'error',
                        message: 'Preview audio was generated, but browser playback failed.',
                        autoClose: true,
                    });
                });
            },
            error: async (error: any) => {
                const message = await this.extractPreviewErrorMessage(error);
                this.notificationService.open({
                    title: 'Voice preview error',
                    type: 'error',
                    message,
                    autoClose: true,
                });
                this.cdr.markForCheck();
            }
        });
    }

    private getPreviewValidationMessage(): string {
        if (this.isActiveModule('coqui')) {
            if (!this.getSelectedVoiceFilePath()) {
                return 'Select or import an XTTS voice file before generating a preview.';
            }
            const modelRevision = String(this.getCoquiField('modelRevision')?.value || '').trim();
            const selectedModel = this.localXttsModels.find((item) => item.path === modelRevision);
            if (selectedModel && !selectedModel.installed && !selectedModel.custom) {
                return 'Download and apply the selected XTTS model before generating a preview.';
            }
        }
        return '';
    }

    private async extractPreviewErrorMessage(error: any): Promise<string> {
        const fallback = 'Failed to generate preview';
        const rawError = error?.error;

        if (rawError instanceof Blob) {
            try {
                const text = await rawError.text();
                if (!text.trim()) {
                    return fallback;
                }
                try {
                    const payload = JSON.parse(text);
                    return payload?.detail || payload?.message || text;
                } catch {
                    return text;
                }
            } catch {
                return fallback;
            }
        }

        return rawError?.detail || rawError?.message || error?.message || fallback;
    }

    stopPreview(): void {
        if (this.previewAudio) {
            this.previewAudio.pause();
            this.previewAudio.currentTime = 0;
            this.previewAudio = null;
        }
    }

    private syncLocalAudioVolumes(): void {
        const volume = this.getNormalizedPreviewVolume();
        if (this.previewAudio) {
            this.previewAudio.volume = volume;
        }
        if (this.sampleAudio) {
            this.sampleAudio.volume = volume;
        }
    }

    private getNormalizedPreviewVolume(): number {
        const rawValue = Number(this.getCoquiField('volume')?.value ?? 1);
        if (!Number.isFinite(rawValue)) {
            return 1;
        }
        return Math.min(1, Math.max(0, rawValue));
    }
}
