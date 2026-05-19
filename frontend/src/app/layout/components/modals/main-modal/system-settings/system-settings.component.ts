import { Component, OnInit } from '@angular/core';
import { UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { ConfigService, SystemCharacter } from '../../../../../core/services/config.service';
import { ThemeService } from '../../../../../core/services/theme.service';
import { combineLatest, BehaviorSubject, forkJoin } from 'rxjs';
import { map, tap, finalize } from 'rxjs/operators';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';
import { TunnelService, TunnelStatus } from '../../../../../core/services/tunnel.service';
import { UiNotificationService } from '../../../../../shared/ui/services/ui-notification.service';

@Component({
    selector: 'app-system-settings',
    templateUrl: './system-settings.component.html',
    styleUrls: ['./system-settings.component.less']
})
export class SystemSettingsComponent implements OnInit {
    systemForm: UntypedFormGroup;
    originalConfig: any = {};
    isLoading$ = new BehaviorSubject<boolean>(true);
    isCharacterImportBusy = false;
    isCharacterCreateBusy = false;
    isCharacterDeleteBusy = false;
    showCreateCharacterModal = false;
    newCharacterName = '';
    tunnelStatus: TunnelStatus | null = null;
    isTunnelBusy = false;
    selectedCharacterFile: File | null = null;
    characterOptions: UiSelectOption[] = [];
    private characterPromptMap = new Map<string, string>();
    private characterIdToPromptMap = new Map<string, string>();
    private characterIdToNameMap = new Map<string, string>();
    readonly languageOptions: UiSelectOption[] = [
        { value: 'en-US', label: 'English (US)' },
        { value: 'ru-RU', label: 'Russian' },
    ];
    readonly tunnelingProviderOptions: UiSelectOption[] = [
        { value: 'cloudflared', label: 'Cloudflared' },
        { value: 'localtunnel', label: 'LocalTunnel (lt)' },
    ];
    readonly communicationPrimaryOptions: UiSelectOption[] = [
        { value: 'main_chat', label: 'Main Chat (core)' },
        { value: 'telegram', label: 'Telegram' },
    ];
    readonly modelMemoryProfileOptions: UiSelectOption[] = [
        { value: 'low_memory_strict', label: 'Low Memory (strict unload)' },
        { value: 'balanced', label: 'Balanced' },
        { value: 'max_speed', label: 'Max Speed (keep loaded)' },
    ];

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private themeService: ThemeService,
        private localizationService: LocalizationService,
        private tunnelService: TunnelService,
        private uiNotificationService: UiNotificationService,
    ) {
        this.systemForm = this.createForm();
    }

    ngOnInit(): void {
        this.initialize();
        this.localizationService.init();
        this.initLanguageChangeListener();
        this.initCommunicationFormRules();
        this.refreshTunnelStatus();
    }

    initLanguageChangeListener() {
        const control = this.systemForm.get('language');
        if (control) {
            control.valueChanges.subscribe(lang => {
                if (lang) {
                    localStorage.setItem('language', lang);
                    this.localizationService.setLanguage(lang);
                }
            });
        }
    }

    private initialize(): void {
        combineLatest([
            this.configService.getConfig$(),
            this.configService.getSystem$(),
            this.configService.getSystemCharacters$(),
        ]).pipe(
            tap(() => this.isLoading$.next(true)),
            map(([config, system, charactersPayload]: [any, any, any]) => {
                const currentTheme = this.themeService.getTheme();
                const activeCharacterId =
                    system?.system?.active_character_id ||
                    charactersPayload?.active_character_id ||
                    null;
                const activeCharName =
                    system?.system?.char_name ||
                    charactersPayload?.active_char_name ||
                    config?.system?.charName ||
                    'Character Name';
                const importedCharacters: SystemCharacter[] =
                    charactersPayload?.characters ||
                    system?.system?.characters ||
                    [];
                const systemPrompt =
                    system?.system?.prompt ||
                    importedCharacters.find((item) => item.name === activeCharName)?.prompt ||
                    'You are a helpful assistant...';
                this.applyCharacterCatalog(
                    importedCharacters,
                    activeCharacterId,
                    activeCharName,
                    systemPrompt
                );
                const combinedConfig = {
                    active_character_id: this.resolveActiveCharacterId(
                        activeCharacterId,
                        activeCharName
                    ),
                    system_prompt: systemPrompt,
                    user_name: config?.system?.userName || 'You',
                    language: config?.system?.language || 'en-US',
                    theme: currentTheme,
                    model_memory_profile:
                        config?.system?.runtime?.modelMemoryProfile || 'low_memory_strict',
                    modules: this.normalizeModulesModel(config?.modules),
                    communication: this.mapCommunicationFromForm(
                        this.mapCommunicationToForm(config?.communication)
                    ),
                    connector: config?.connector || {
                        tunneling: {
                            enabled: false,
                            provider: 'cloudflared',
                            localUrl: 'http://127.0.0.1:3880',
                            localPort: 3880,
                            commandPath: '',
                            publicUrl: '',
                        },
                    },
                };

                return combinedConfig;
            }),
            tap(combinedConfig => {
                this.originalConfig = combinedConfig;
                this.patchFormWithConfig(combinedConfig);
            }),
            finalize(() => this.isLoading$.next(false))
        ).subscribe();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            active_character_id: [''],
            system_prompt: ['You are a helpful assistant. Respond naturally and engage in meaningful conversation.'],
            user_name: ['You'],
            language: ['en-US'],
            theme: ['dark'],
            model_memory_profile: ['low_memory_strict'],
            modules: this.fb.group({
                vtube_studio: [false],
                whisper: [false],
                minecraft: [false],
                gaming: [false],
                alarm: [false],
                discord: [false],
                telegram: [false],
                rag: [false],
                visual: [false]
            }),
            communication: this.fb.group({
                primary_channel: ['main_chat'],
                channels: this.fb.group({
                    main_chat: this.fb.group({
                        enabled: [true],
                        allow_fallback: [false],
                    }),
                    telegram: this.fb.group({
                        enabled: [true],
                        allow_fallback: [true],
                    }),
                }),
            }),
            connector: this.fb.group({
                tunneling: this.fb.group({
                    enabled: [false],
                    provider: ['cloudflared'],
                    localUrl: ['http://127.0.0.1:3880'],
                    localPort: [3880],
                    commandPath: [''],
                    publicUrl: [''],
                }),
            })
        });
    }

    private patchFormWithConfig(config: any): void {
        this.systemForm.patchValue({
            active_character_id: config.active_character_id ?? '',
            system_prompt: config.system_prompt ?? 'You are a helpful assistant. Respond naturally and engage in meaningful conversation.',
            user_name: config.user_name ?? 'You',
            language: config.language ?? 'en-US',
            theme: config.theme ?? 'dark',
            model_memory_profile: config.model_memory_profile ?? 'low_memory_strict',
            modules: this.mapModulesModelToForm(config.modules),
            communication: this.mapCommunicationToForm(config.communication),
            connector: config.connector ?? {},
        });
        this.enforceCommunicationRules(false);
    }

    private buildConfigFromForm(): any {
        const formValue = this.systemForm.value;

        return {
            active_character_id: formValue.active_character_id,
            system_prompt: formValue.system_prompt,
            user_name: formValue.user_name,
            language: formValue.language,
            theme: formValue.theme,
            model_memory_profile: formValue.model_memory_profile,
            modules: this.mapModulesFormToModel(formValue.modules),
            communication: this.mapCommunicationFromForm(formValue.communication),
            connector: formValue.connector,
        };
    }

    saveChanges(): void {
        this.enforceCommunicationRules(false);
        const changes = this.getChanges();
        if (Object.keys(changes).length > 0) {
            const updateData: any = {};
            const requests = [];

            if (changes.system_prompt !== undefined || changes.active_character_id !== undefined) {
                const currentPrompt = this.systemForm.value.system_prompt;
                const nextPrompt = changes.system_prompt !== undefined ? changes.system_prompt : currentPrompt;
                const nextCharacterId =
                    changes.active_character_id !== undefined
                        ? changes.active_character_id
                        : this.systemForm.value.active_character_id;
                requests.push(
                    this.configService.updateSystem$(nextPrompt, undefined, nextCharacterId)
                );
            }
            if (changes.user_name !== undefined) {
                updateData.system = updateData.system || {};
                updateData.system.userName = changes.user_name;
            }
            if (changes.language !== undefined) {
                updateData.system = updateData.system || {};
                updateData.system.language = changes.language;
                this.localizationService.setLanguage(changes.language);
            }
            if (changes.theme !== undefined) {
                this.themeService.setTheme(changes.theme);
                updateData.system = updateData.system || {};
                updateData.system.theme = changes.theme;
            }
            if (changes.model_memory_profile !== undefined) {
                updateData.system = updateData.system || {};
                updateData.system.runtime = updateData.system.runtime || {};
                updateData.system.runtime.modelMemoryProfile = changes.model_memory_profile;
            }
            if (changes.modules !== undefined) {
                updateData.modules = changes.modules;
            }
            if (changes.communication !== undefined) {
                updateData.communication = changes.communication;
            }
            if (changes.connector !== undefined) {
                updateData.connector = changes.connector;
            }

            if (Object.keys(updateData).length > 0) {
                requests.push(this.configService.updateConfig$(updateData));
            }

            if (requests.length === 0) {
                return;
            }

            forkJoin(requests).subscribe({
                next: () => {
                    this.originalConfig = this.buildConfigFromForm();
                    this.uiNotificationService.success('Settings saved', 'System');
                },
                error: (error) => {
                    console.error('Error updating system settings:', error);
                    this.uiNotificationService.error('Failed to save settings', 'System');
                }
            });
        }
    }

    private getChanges(): any {
        const current = this.buildConfigFromForm();
        const changes: any = {};

        for (const key in current) {
            if (JSON.stringify(current[key]) !== JSON.stringify(this.originalConfig[key])) {
                changes[key] = current[key];
            }
        }

        return changes;
    }

    hasChanges(): boolean {
        return Object.keys(this.getChanges()).length > 0;
    }

    onThemeChange(event: any): void {
        const selectedTheme = event.target.value as 'dark' | 'light';
        this.themeService.setTheme(selectedTheme);
        this.systemForm.get('theme')?.setValue(selectedTheme);
    }

    private normalizeModulesModel(modules: any): any {
        const source = modules || {};
        return {
            vtubeStudio: !!(source.vtubeStudio ?? source.vtube_studio),
            whisper: !!source.whisper,
            minecraft: !!source.minecraft,
            gaming: !!source.gaming,
            alarm: !!source.alarm,
            discord: !!source.discord,
            telegram: !!source.telegram,
            rag: !!source.rag,
            visual: !!source.visual,
        };
    }

    private mapModulesModelToForm(modules: any): any {
        const normalized = this.normalizeModulesModel(modules);
        return {
            vtube_studio: normalized.vtubeStudio,
            whisper: normalized.whisper,
            minecraft: normalized.minecraft,
            gaming: normalized.gaming,
            alarm: normalized.alarm,
            discord: normalized.discord,
            telegram: normalized.telegram,
            rag: normalized.rag,
            visual: normalized.visual,
        };
    }

    private mapModulesFormToModel(modules: any): any {
        const source = modules || {};
        const existing = this.normalizeModulesModel(this.originalConfig?.modules || {});
        return {
            ...existing,
            vtubeStudio: !!source.vtube_studio,
        };
    }

    onCharacterChange(event: { target: { value: string } }): void {
        const nextId = String(event?.target?.value || '').trim();
        if (!nextId) {
            return;
        }
        const prompt =
            this.characterIdToPromptMap.get(nextId) ||
            this.characterPromptMap.get(this.characterIdToNameMap.get(nextId) || '');
        if (typeof prompt === 'string') {
            this.systemForm.patchValue({ system_prompt: prompt });
        }
    }

    onCharacterFileSelected(event: Event): void {
        const target = event.target as HTMLInputElement | null;
        this.selectedCharacterFile = target?.files?.[0] || null;
    }

    importCharacterYaml(): void {
        if (this.isCharacterImportBusy || !this.selectedCharacterFile) {
            return;
        }
        this.isCharacterImportBusy = true;
        this.readFileAsText(this.selectedCharacterFile)
            .then((content) => {
                return this.configService
                    .importSystemCharacterYaml$(this.selectedCharacterFile!.name, content, true)
                    .toPromise();
            })
            .then((response: any) => {
                const importedName = response?.character?.name;
                const importedPrompt = response?.character?.prompt || '';
                if (importedName) {
                    this.characterPromptMap.set(importedName, importedPrompt);
                    this.applyCharacterCatalog(
                        [
                            ...Array.from(this.characterPromptMap.entries()).map(([name, prompt]) => ({
                                name,
                                prompt,
                            })),
                        ],
                        response?.active_character_id || null,
                        importedName,
                        importedPrompt
                    );
                    this.systemForm.patchValue({
                        active_character_id:
                            response?.active_character_id || this.resolveActiveCharacterId(undefined, importedName),
                        system_prompt: importedPrompt,
                    });
                    this.uiNotificationService.success(importedName, 'Character imported');
                } else {
                    this.uiNotificationService.success('YAML imported', 'Character');
                }
            })
            .catch((error) => {
                console.error('Character import error:', error);
                const detail = error?.error?.detail || 'Failed to import character YAML';
                this.uiNotificationService.error(detail, 'Character import');
            })
            .finally(() => {
                this.isCharacterImportBusy = false;
                this.selectedCharacterFile = null;
            });
    }

    openCreateCharacterModal(): void {
        this.newCharacterName = '';
        this.showCreateCharacterModal = true;
    }

    closeCreateCharacterModal(): void {
        if (this.isCharacterCreateBusy) {
            return;
        }
        this.showCreateCharacterModal = false;
        this.newCharacterName = '';
    }

    createCharacter(): void {
        const name = String(this.newCharacterName || '').trim();
        if (!name || this.isCharacterCreateBusy) {
            return;
        }

        this.isCharacterCreateBusy = true;
        this.configService.createSystemCharacter$(name, true).subscribe({
            next: (response: any) => {
                const character = response?.character;
                const characterName = character?.name || name;
                const characterPrompt = character?.prompt || '';
                if (character?.id) {
                    this.characterPromptMap.set(characterName, characterPrompt);
                    this.characterIdToPromptMap.set(String(character.id), characterPrompt);
                    this.characterIdToNameMap.set(String(character.id), characterName);
                    this.rebuildCharacterOptions(response?.active_character_id || character.id, characterName, characterPrompt);
                    this.systemForm.patchValue({
                        active_character_id: response?.active_character_id || character.id,
                        system_prompt: characterPrompt,
                    });
                    this.originalConfig = {
                        ...this.originalConfig,
                        active_character_id: response?.active_character_id || character.id,
                        system_prompt: characterPrompt,
                    };
                }
                this.showCreateCharacterModal = false;
                this.newCharacterName = '';
                this.uiNotificationService.success(characterName, 'Character created');
            },
            error: (error) => {
                console.error('Character create error:', error);
                this.uiNotificationService.error(error?.error?.detail || 'Failed to create character', 'Character');
            },
            complete: () => {
                this.isCharacterCreateBusy = false;
            },
        });
    }

    deleteSelectedCharacter(): void {
        const characterId = String(this.systemForm.get('active_character_id')?.value || '').trim();
        if (!characterId || this.isCharacterDeleteBusy) {
            return;
        }
        const characterName = this.characterIdToNameMap.get(characterId) || characterId;
        if (!window.confirm(`Delete character "${characterName}"?`)) {
            return;
        }

        this.isCharacterDeleteBusy = true;
        this.configService.deleteSystemCharacter$(characterId).subscribe({
            next: (response: any) => {
                const characters = response?.characters || [];
                const activeName = response?.active_char_name || characters[0]?.name || '';
                const activeId = response?.active_character_id || characters[0]?.id || null;
                const activePrompt =
                    characters.find((item: SystemCharacter) => item.id === activeId)?.prompt ||
                    characters.find((item: SystemCharacter) => item.name === activeName)?.prompt ||
                    '';
                this.applyCharacterCatalog(characters, activeId, activeName, activePrompt);
                this.systemForm.patchValue({
                    active_character_id: this.resolveActiveCharacterId(activeId, activeName),
                    system_prompt: activePrompt,
                });
                this.originalConfig = this.buildConfigFromForm();
                this.uiNotificationService.success(characterName, 'Character deleted');
            },
            error: (error) => {
                console.error('Character delete error:', error);
                this.uiNotificationService.error(error?.error?.detail || 'Failed to delete character', 'Character');
            },
            complete: () => {
                this.isCharacterDeleteBusy = false;
            },
        });
    }

    private applyCharacterCatalog(
        characters: SystemCharacter[],
        activeId: string | null | undefined,
        activeName: string,
        fallbackPrompt: string,
    ): void {
        this.characterPromptMap.clear();
        this.characterIdToPromptMap.clear();
        this.characterIdToNameMap.clear();
        (characters || []).forEach((item) => {
            const name = (item?.name || '').trim();
            if (!name) {
                return;
            }
            const itemId = String(item?.id || name).trim();
            this.characterPromptMap.set(name, item.prompt || '');
            this.characterIdToPromptMap.set(itemId, item.prompt || '');
            this.characterIdToNameMap.set(itemId, name);
        });
        if (activeName && !this.characterPromptMap.has(activeName)) {
            this.characterPromptMap.set(activeName, fallbackPrompt || '');
            const fallbackId = String(activeId || activeName).trim();
            this.characterIdToPromptMap.set(fallbackId, fallbackPrompt || '');
            this.characterIdToNameMap.set(fallbackId, activeName);
        }
        this.rebuildCharacterOptions(activeId, activeName, fallbackPrompt);
    }

    private rebuildCharacterOptions(activeId?: string | null, activeName?: string, activePrompt?: string): void {
        if (activeName && !this.characterPromptMap.has(activeName)) {
            this.characterPromptMap.set(activeName, activePrompt || '');
            const fallbackId = String(activeId || activeName).trim();
            this.characterIdToPromptMap.set(fallbackId, activePrompt || '');
            this.characterIdToNameMap.set(fallbackId, activeName);
        }
        this.characterOptions = Array.from(this.characterIdToNameMap.entries())
            .sort((a, b) => a[1].localeCompare(b[1]))
            .map(([id, name]) => ({ value: id, label: name }));
    }

    private resolveActiveCharacterId(activeId?: string | null, activeName?: string): string {
        if (activeId && this.characterIdToNameMap.has(activeId)) {
            return activeId;
        }
        if (activeName) {
            const found = Array.from(this.characterIdToNameMap.entries()).find(
                ([, name]) => name === activeName
            );
            if (found) {
                return found[0];
            }
        }
        const first = this.characterOptions[0]?.value;
        return typeof first === 'string' ? first : '';
    }

    private readFileAsText(file: File): Promise<string> {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onerror = () => reject(new Error('Unable to read file'));
            reader.onload = () => resolve(String(reader.result || ''));
            reader.readAsText(file);
        });
    }

    refreshTunnelStatus(): void {
        this.isTunnelBusy = true;
        this.tunnelService.getStatus$().subscribe({
            next: (status) => {
                this.tunnelStatus = status;
                this.syncTunnelPublicUrl(status.public_url || '');
                this.isTunnelBusy = false;
            },
            error: (error) => {
                console.error('Tunnel status error:', error);
                this.isTunnelBusy = false;
            },
        });
    }

    startTunnel(): void {
        const cfg = this.systemForm.get('connector.tunneling')?.value || {};
        const overrides = {
            enabled: !!cfg.enabled,
            provider: cfg.provider || 'cloudflared',
            local_url: cfg.localUrl || 'http://127.0.0.1:3880',
            local_port: Number(cfg.localPort) || 3880,
            command_path: cfg.commandPath || '',
            public_url: cfg.publicUrl || '',
        };

        this.isTunnelBusy = true;
        this.tunnelService.start$(overrides).subscribe({
            next: (status) => {
                this.tunnelStatus = status;
                this.syncTunnelPublicUrl(status.public_url || '');
                this.isTunnelBusy = false;
                if (status.last_error && !status.running) {
                    this.uiNotificationService.error(status.last_error, 'Tunnel');
                    return;
                }
                if (status.public_url) {
                    this.uiNotificationService.success(status.public_url, 'Tunnel started');
                } else {
                    this.uiNotificationService.success('Tunnel process started', 'Tunnel');
                }
            },
            error: (error) => {
                console.error('Tunnel start error:', error);
                this.isTunnelBusy = false;
                this.uiNotificationService.error('Failed to start tunnel', 'Tunnel');
            },
        });
    }

    stopTunnel(): void {
        this.isTunnelBusy = true;
        this.tunnelService.stop$().subscribe({
            next: (status) => {
                this.tunnelStatus = status;
                this.syncTunnelPublicUrl(status.public_url || '');
                this.isTunnelBusy = false;
                this.uiNotificationService.success('Tunnel stopped', 'Tunnel');
            },
            error: (error) => {
                console.error('Tunnel stop error:', error);
                this.isTunnelBusy = false;
                this.uiNotificationService.error('Failed to stop tunnel', 'Tunnel');
            },
        });
    }

    private syncTunnelPublicUrl(url: string): void {
        this.systemForm.get('connector.tunneling.publicUrl')?.setValue(url, { emitEvent: false });
        if (this.originalConfig?.connector?.tunneling) {
            this.originalConfig.connector.tunneling.publicUrl = url;
        }
    }

    private initCommunicationFormRules(): void {
        const primaryControl = this.systemForm.get('communication.primary_channel');
        const mainEnabledControl = this.systemForm.get('communication.channels.main_chat.enabled');
        const telegramEnabledControl = this.systemForm.get('communication.channels.telegram.enabled');

        this.syncTelegramFallbackControlState();
        primaryControl?.valueChanges.subscribe(() => this.enforceCommunicationRules(true));
        mainEnabledControl?.valueChanges.subscribe(() => this.enforceCommunicationRules(true));
        telegramEnabledControl?.valueChanges.subscribe(() => this.enforceCommunicationRules(true));
    }

    private enforceCommunicationRules(notify: boolean): void {
        const primary = String(this.systemForm.get('communication.primary_channel')?.value || 'main_chat');
        const mainPath = 'communication.channels.main_chat.enabled';
        const telegramPath = 'communication.channels.telegram.enabled';
        const telegramFallbackPath = 'communication.channels.telegram.allow_fallback';

        const mainEnabled = !!this.systemForm.get(mainPath)?.value;
        const telegramEnabled = !!this.systemForm.get(telegramPath)?.value;

        if (!mainEnabled && !telegramEnabled) {
            const fallbackChannel = primary === 'telegram' ? telegramPath : mainPath;
            this.systemForm.get(fallbackChannel)?.setValue(true, { emitEvent: false });
            if (notify) {
                this.uiNotificationService.error('At least one channel must stay enabled', 'Communication policy');
            }
        }

        if (primary === 'main_chat') {
            this.systemForm.get(telegramFallbackPath)?.setValue(false, { emitEvent: false });
        }

        if (primary === 'telegram' && !this.systemForm.get(telegramPath)?.value) {
            this.systemForm.get(telegramPath)?.setValue(true, { emitEvent: false });
        }
        if (primary === 'main_chat' && !this.systemForm.get(mainPath)?.value) {
            this.systemForm.get(mainPath)?.setValue(true, { emitEvent: false });
        }

        this.syncTelegramFallbackControlState();
    }

    private syncTelegramFallbackControlState(): void {
        const primary = String(this.systemForm.get('communication.primary_channel')?.value || 'main_chat');
        const fallbackControl = this.systemForm.get('communication.channels.telegram.allow_fallback');
        if (!fallbackControl) {
            return;
        }

        if (primary === 'main_chat') {
            fallbackControl.disable({ emitEvent: false });
            fallbackControl.setValue(false, { emitEvent: false });
            return;
        }

        fallbackControl.enable({ emitEvent: false });
    }

    private mapCommunicationToForm(communication: any): any {
        const source = communication && typeof communication === 'object' ? communication : {};
        const priorityRaw = Array.isArray(source.priority) ? source.priority : [];
        const primary =
            String(priorityRaw[0] || 'main_chat') === 'telegram' ? 'telegram' : 'main_chat';
        const channels = source.channels && typeof source.channels === 'object' ? source.channels : {};
        const mainCfg = channels.main_chat && typeof channels.main_chat === 'object' ? channels.main_chat : {};
        const telegramCfg = channels.telegram && typeof channels.telegram === 'object' ? channels.telegram : {};
        return {
            primary_channel: primary,
            channels: {
                main_chat: {
                    enabled: mainCfg.enabled !== undefined ? !!mainCfg.enabled : true,
                    allow_fallback: false,
                },
                telegram: {
                    enabled: telegramCfg.enabled !== undefined ? !!telegramCfg.enabled : true,
                    allow_fallback:
                        primary === 'main_chat'
                            ? false
                            : telegramCfg.allow_fallback !== undefined
                              ? !!telegramCfg.allow_fallback
                              : true,
                },
            },
        };
    }

    private mapCommunicationFromForm(formValue: any): any {
        const data = formValue && typeof formValue === 'object' ? formValue : {};
        const primary = String(data.primary_channel || 'main_chat') === 'telegram' ? 'telegram' : 'main_chat';
        const channels = data.channels && typeof data.channels === 'object' ? data.channels : {};
        const mainCfg = channels.main_chat && typeof channels.main_chat === 'object' ? channels.main_chat : {};
        const telegramCfg = channels.telegram && typeof channels.telegram === 'object' ? channels.telegram : {};

        const mainEnabled = mainCfg.enabled !== undefined ? !!mainCfg.enabled : true;
        const telegramEnabled = telegramCfg.enabled !== undefined ? !!telegramCfg.enabled : true;
        if (!mainEnabled && !telegramEnabled) {
            if (primary === 'telegram') {
                return {
                    priority: ['telegram', 'main_chat'],
                    channels: {
                        main_chat: { enabled: false, allow_fallback: false },
                        telegram: { enabled: true, allow_fallback: true },
                    },
                };
            }
            return {
                priority: ['main_chat', 'telegram'],
                channels: {
                    main_chat: { enabled: true, allow_fallback: false },
                    telegram: { enabled: false, allow_fallback: false },
                },
            };
        }

        return {
            priority: primary === 'telegram' ? ['telegram', 'main_chat'] : ['main_chat', 'telegram'],
            channels: {
                main_chat: {
                    enabled: mainEnabled,
                    allow_fallback: false,
                },
                telegram: {
                    enabled: telegramEnabled,
                    allow_fallback: primary === 'main_chat' ? false : !!telegramCfg.allow_fallback,
                },
            },
        };
    }

    get themeOptions(): UiSelectOption[] {
        return [
            {
                value: 'dark',
                label: `${this.localizationService.t('settings.theme')} - ${this.localizationService.t('general.dark')}`,
            },
            {
                value: 'light',
                label: `${this.localizationService.t('settings.theme')} - ${this.localizationService.t('general.light')}`,
            },
        ];
    }
}
