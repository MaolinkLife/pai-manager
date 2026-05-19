import { Component, OnInit } from '@angular/core';
import { UntypedFormArray, UntypedFormBuilder, UntypedFormGroup } from '@angular/forms';
import { BehaviorSubject, forkJoin } from 'rxjs';
import { finalize } from 'rxjs/operators';
import { ConfigService, SystemCharacter } from '../../../../../core/services/config.service';
import { TelegramChatPeer, TelegramService } from '../../../../../core/services/telegram.service';
import { UiSelectOption } from '../../../../../shared/ui/components/ui-select/ui-select.component';
import { LocalizationService } from '../../../../../shared/pipes/translation/localization.service';
import { UiNotificationService } from '../../../../../shared/ui/services/ui-notification.service';

@Component({
    selector: 'app-persona-settings',
    templateUrl: './persona-settings.component.html',
    styleUrls: ['./persona-settings.component.less']
})
export class PersonaSettingsComponent implements OnInit {
    personaForm: UntypedFormGroup;
    originalState: any = {};
    isLoading$ = new BehaviorSubject<boolean>(true);
    isCharacterImportBusy = false;
    isCharacterCreateBusy = false;
    isCharacterDeleteBusy = false;
    isChatsLoading = false;
    showCreateCharacterModal = false;
    newCharacterName = '';
    selectedCharacterFile: File | null = null;
    characterOptions: UiSelectOption[] = [];

    readonly stylePresetOptions: UiSelectOption[] = [
        { value: 'anime', label: 'Anime' },
        { value: 'semi_real_anime', label: 'Semi-real anime' },
        { value: 'illustration', label: 'Illustration' },
    ];
    readonly renderProfileOptions: UiSelectOption[] = [
        { value: 'default_anime', label: 'Default anime' },
        { value: 'portrait_soft', label: 'Portrait soft' },
        { value: 'cozy_home', label: 'Cozy home' },
    ];

    get characterBindingOptions(): UiSelectOption[] {
        return [
            { value: '', label: this.localizationService.t('personaSettings.useActivePersona') },
            ...this.characterOptions,
        ];
    }

    private synthesisSnapshot: any = {};
    private telegramSnapshot: any = {};
    private activeCharacterName = 'PAI';
    private perCharacterVisualProfiles: Record<string, any> = {};
    private characterPromptMap = new Map<string, string>();
    private characterIdToPromptMap = new Map<string, string>();
    private characterIdToNameMap = new Map<string, string>();

    constructor(
        private fb: UntypedFormBuilder,
        private configService: ConfigService,
        private telegramService: TelegramService,
        private localizationService: LocalizationService,
        private uiNotificationService: UiNotificationService,
    ) {
        this.personaForm = this.createForm();
    }

    ngOnInit(): void {
        this.localizationService.init();
        this.loadConfig();
    }

    private createForm(): UntypedFormGroup {
        return this.fb.group({
            active_character_id: [''],
            system_prompt: [''],
            chat_bindings: this.fb.array([]),
            visual_profile: this.fb.group({
                character_name: ['PAI'],
                appearance_textarea: [''],
                default_outfit: [''],
                default_environment: [''],
                style_preset: ['anime'],
                render_profile: ['default_anime'],
                selfie_bias: [0.85],
                environment_bias: [0.10],
                symbolic_bias: [0.05],
                anti_repetition_strength: [0.65],
                use_time_of_day: [true],
                use_season: [true],
                use_weather: [true],
                use_relation_state: [true],
                use_recent_topics: [true],
                selfie_composition_base: [''],
                selfie_composition_pool_override: [''],
                environment_composition_pool_override: [''],
                allow_self_images: [true],
                allow_environment_images: [true],
                allow_symbolic_images: [true],
            }),
        });
    }

    get chatBindingControls(): UntypedFormArray {
        return this.personaForm.get('chat_bindings') as UntypedFormArray;
    }

    private loadConfig(): void {
        forkJoin({
            config: this.configService.getConfig$(),
            system: this.configService.getSystem$(),
            charactersPayload: this.configService.getSystemCharacters$(),
        }).pipe(
            finalize(() => this.isLoading$.next(false))
        ).subscribe({
            next: ({ config, system, charactersPayload }: any) => {
                this.synthesisSnapshot = config?.synthesis || {};
                this.telegramSnapshot = config?.telegram || {};
                const activeCharacterId =
                    system?.system?.active_character_id ||
                    charactersPayload?.active_character_id ||
                    null;
                const activeCharName =
                    system?.system?.char_name ||
                    charactersPayload?.active_char_name ||
                    config?.system?.charName ||
                    'PAI';
                const importedCharacters: SystemCharacter[] =
                    charactersPayload?.characters ||
                    system?.system?.characters ||
                    [];
                const systemPrompt =
                    system?.system?.prompt ||
                    importedCharacters.find((item) => item.name === activeCharName)?.prompt ||
                    '';

                this.applyCharacterCatalog(importedCharacters, activeCharacterId, activeCharName, systemPrompt);
                this.perCharacterVisualProfiles = {
                    ...(this.synthesisSnapshot?.prompting?.per_character_visual_profiles || {}),
                };
                this.activeCharacterName = activeCharName;
                this.patchFormForCharacter(
                    this.resolveActiveCharacterId(activeCharacterId, activeCharName),
                    activeCharName,
                    systemPrompt,
                );
                this.originalState = this.buildStateForSave();
                this.loadTelegramChats();
            },
            error: (error) => {
                console.error('Persona settings load error:', error);
                this.uiNotificationService.error(
                    this.localizationService.t('personaSettings.loadFailedMessage'),
                    this.localizationService.t('personaSettings.title'),
                );
            },
        });
    }

    private loadTelegramChats(): void {
        this.isChatsLoading = true;
        this.telegramService.listChats$(200, true).subscribe({
            next: (payload) => {
                this.patchChatBindings(payload?.chats || []);
                this.originalState = this.buildStateForSave();
                this.isChatsLoading = false;
            },
            error: (error) => {
                console.error('Persona Telegram chats load error:', error);
                this.patchChatBindings([]);
                this.isChatsLoading = false;
            },
        });
    }

    private patchChatBindings(chats: TelegramChatPeer[]): void {
        const controls = this.chatBindingControls;
        while (controls.length) {
            controls.removeAt(0);
        }
        const map = this.telegramSnapshot?.persona_bindings?.chat_character_map || {};
        (chats || [])
            .slice()
            .sort((a, b) => String(a.title || a.chat_id).localeCompare(String(b.title || b.chat_id)))
            .forEach((chat) => {
                const chatId = String(chat.chat_id);
                controls.push(
                    this.fb.group({
                        chat_id: [chatId],
                        title: [chat.title || chatId],
                        chat_kind: [chat.chat_kind || 'unknown'],
                        username: [chat.username || ''],
                        character_id: [String(map?.[chatId] || '')],
                    }),
                );
            });
    }

    onCharacterChange(event: { target: { value: string } }): void {
        const nextId = String(event?.target?.value || '').trim();
        if (!nextId) {
            return;
        }
        this.cacheCurrentVisualProfile();
        const characterName = this.characterIdToNameMap.get(nextId) || this.activeCharacterName;
        const prompt =
            this.characterIdToPromptMap.get(nextId) ||
            this.characterPromptMap.get(characterName) ||
            '';
        this.patchFormForCharacter(nextId, characterName, prompt);
    }

    saveChanges(): void {
        const nextState = this.buildStateForSave();
        if (JSON.stringify(nextState) === JSON.stringify(this.originalState)) {
            return;
        }

        const requests = [];
        const configUpdate: any = {};
        if (
            nextState.active_character_id !== this.originalState.active_character_id ||
            nextState.system_prompt !== this.originalState.system_prompt
        ) {
            requests.push(
                this.configService.updateSystem$(
                    nextState.system_prompt,
                    undefined,
                    nextState.active_character_id,
                )
            );
        }
        if (JSON.stringify(nextState.synthesis) !== JSON.stringify(this.originalState.synthesis)) {
            configUpdate.synthesis = nextState.synthesis;
        }
        if (JSON.stringify(nextState.telegram) !== JSON.stringify(this.originalState.telegram)) {
            configUpdate.telegram = nextState.telegram;
        }
        if (Object.keys(configUpdate).length > 0) {
            requests.push(this.configService.updateConfig$(configUpdate));
        }

        if (!requests.length) {
            return;
        }

        forkJoin(requests).subscribe({
            next: () => {
                this.configService.invalidateConfig();
                this.synthesisSnapshot = nextState.synthesis;
                this.telegramSnapshot = nextState.telegram;
                this.perCharacterVisualProfiles =
                    nextState.synthesis?.prompting?.per_character_visual_profiles || {};
                this.originalState = this.buildStateForSave();
                this.uiNotificationService.success(
                    this.localizationService.t('personaSettings.savedMessage'),
                    this.localizationService.t('personaSettings.title'),
                );
            },
            error: (error) => {
                console.error('Persona settings save error:', error);
                this.uiNotificationService.error(
                    this.localizationService.t('personaSettings.saveFailedMessage'),
                    this.localizationService.t('personaSettings.title'),
                );
            },
        });
    }

    hasChanges(): boolean {
        return JSON.stringify(this.buildStateForSave()) !== JSON.stringify(this.originalState);
    }

    onCharacterFileSelected(event: Event): void {
        const target = event.target as HTMLInputElement | null;
        this.selectedCharacterFile = target?.files?.[0] || null;
    }

    importCharacterYaml(): void {
        if (this.isCharacterImportBusy || !this.selectedCharacterFile) {
            return;
        }
        const file = this.selectedCharacterFile;
        this.isCharacterImportBusy = true;
        this.readFileAsText(file)
            .then((content) => this.configService.importSystemCharacterYaml$(file.name, content, true).toPromise())
            .then((response: any) => {
                const importedName = response?.character?.name;
                const importedPrompt = response?.character?.prompt || '';
                const importedId = response?.active_character_id || response?.character?.id || importedName;
                if (importedName) {
                    this.characterPromptMap.set(importedName, importedPrompt);
                    this.characterIdToPromptMap.set(String(importedId), importedPrompt);
                    this.characterIdToNameMap.set(String(importedId), importedName);
                    this.rebuildCharacterOptions(importedId, importedName, importedPrompt);
                    this.patchFormForCharacter(String(importedId), importedName, importedPrompt);
                    this.uiNotificationService.success(importedName, 'Character imported');
                } else {
                    this.uiNotificationService.success('YAML imported', 'Character');
                }
            })
            .catch((error) => {
                console.error('Character import error:', error);
                this.uiNotificationService.error(
                    error?.error?.detail || 'Failed to import character YAML',
                    'Character import',
                );
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
                const characterId = String(response?.active_character_id || character?.id || characterName);
                this.characterPromptMap.set(characterName, characterPrompt);
                this.characterIdToPromptMap.set(characterId, characterPrompt);
                this.characterIdToNameMap.set(characterId, characterName);
                this.rebuildCharacterOptions(characterId, characterName, characterPrompt);
                this.patchFormForCharacter(characterId, characterName, characterPrompt);
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
        const characterId = String(this.personaForm.get('active_character_id')?.value || '').trim();
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
                this.removeVisualProfile(characterName);
                this.patchFormForCharacter(this.resolveActiveCharacterId(activeId, activeName), activeName, activePrompt);
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

    private patchFormForCharacter(characterId: string, characterName: string, systemPrompt: string): void {
        const name = String(characterName || 'PAI').trim() || 'PAI';
        this.activeCharacterName = name;
        const profile = this.resolveVisualProfile(name);
        this.personaForm.patchValue({
            active_character_id: characterId || '',
            system_prompt: systemPrompt || '',
            visual_profile: profile,
        });
    }

    private resolveVisualProfile(characterName: string): any {
        const prompting = this.synthesisSnapshot?.prompting || {};
        const fallbackProfile = prompting?.visual_profile || {};
        const hasProfile = this.perCharacterVisualProfiles[characterName] !== undefined;
        const fallbackMatchesCharacter =
            String(fallbackProfile?.character_name || '').trim() === String(characterName || '').trim();
        const profile = hasProfile
            ? this.perCharacterVisualProfiles[characterName]
            : fallbackMatchesCharacter
              ? fallbackProfile
              : {};
        return {
            character_name: characterName || profile.character_name || 'PAI',
            appearance_textarea: profile.appearance_textarea || (fallbackMatchesCharacter ? prompting.appearance_prompt : '') || '',
            default_outfit: profile.default_outfit || '',
            default_environment: profile.default_environment || '',
            style_preset: profile.style_preset || 'anime',
            render_profile: profile.render_profile || 'default_anime',
            selfie_bias: profile.selfie_bias ?? 0.85,
            environment_bias: profile.environment_bias ?? 0.10,
            symbolic_bias: profile.symbolic_bias ?? 0.05,
            anti_repetition_strength: profile.anti_repetition_strength ?? 0.65,
            use_time_of_day: profile.use_time_of_day !== false,
            use_season: profile.use_season !== false,
            use_weather: profile.use_weather !== false,
            use_relation_state: profile.use_relation_state !== false,
            use_recent_topics: profile.use_recent_topics !== false,
            selfie_composition_base: profile.selfie_composition_base || '',
            selfie_composition_pool_override: profile.selfie_composition_pool_override || '',
            environment_composition_pool_override: profile.environment_composition_pool_override || '',
            allow_self_images: profile.allow_self_images !== false,
            allow_environment_images: profile.allow_environment_images !== false,
            allow_symbolic_images: profile.allow_symbolic_images !== false,
        };
    }

    private buildStateForSave(): any {
        const value = this.personaForm.value || {};
        const profileName = String(this.activeCharacterName || value.visual_profile?.character_name || 'PAI').trim() || 'PAI';
        const profile = {
            ...(value.visual_profile || {}),
            character_name: String(value.visual_profile?.character_name || profileName).trim() || profileName,
        };
        const perCharacter = {
            ...this.perCharacterVisualProfiles,
            [profileName]: profile,
        };
        const synthesis = {
            ...(this.synthesisSnapshot || {}),
            prompting: {
                ...(this.synthesisSnapshot?.prompting || {}),
                visual_profile: profile,
                per_character_visual_profiles: perCharacter,
                appearance_prompt: profile.appearance_textarea || this.synthesisSnapshot?.prompting?.appearance_prompt || '',
            },
        };
        return {
            active_character_id: value.active_character_id || '',
            system_prompt: value.system_prompt || '',
            synthesis,
            telegram: this.buildTelegramForSave(),
        };
    }

    private cacheCurrentVisualProfile(): void {
        const value = this.personaForm.value || {};
        const characterName = String(this.activeCharacterName || '').trim();
        if (!characterName) {
            return;
        }
        const visualProfile = value.visual_profile;
        if (!visualProfile || typeof visualProfile !== 'object') {
            return;
        }
        this.perCharacterVisualProfiles = {
            ...this.perCharacterVisualProfiles,
            [characterName]: {
                ...visualProfile,
                character_name: String(visualProfile.character_name || characterName).trim() || characterName,
            },
        };
    }

    private buildTelegramForSave(): any {
        const chatCharacterMap: Record<string, string> = {};
        this.chatBindingControls.controls.forEach((control) => {
            const raw = control.value || {};
            const chatId = String(raw.chat_id || '').trim();
            const characterId = String(raw.character_id || '').trim();
            if (chatId && characterId) {
                chatCharacterMap[chatId] = characterId;
            }
        });
        return {
            ...(this.telegramSnapshot || {}),
            persona_bindings: {
                ...(this.telegramSnapshot?.persona_bindings || {}),
                chat_character_map: chatCharacterMap,
            },
        };
    }

    private removeVisualProfile(characterName: string): void {
        const nextProfiles = { ...this.perCharacterVisualProfiles };
        delete nextProfiles[characterName];
        this.perCharacterVisualProfiles = nextProfiles;
        this.synthesisSnapshot = {
            ...(this.synthesisSnapshot || {}),
            prompting: {
                ...(this.synthesisSnapshot?.prompting || {}),
                per_character_visual_profiles: nextProfiles,
            },
        };
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
            const fallbackId = String(activeId || activeName).trim();
            this.characterPromptMap.set(activeName, fallbackPrompt || '');
            this.characterIdToPromptMap.set(fallbackId, fallbackPrompt || '');
            this.characterIdToNameMap.set(fallbackId, activeName);
        }
        this.rebuildCharacterOptions(activeId, activeName, fallbackPrompt);
    }

    private rebuildCharacterOptions(activeId?: string | null, activeName?: string, activePrompt?: string): void {
        if (activeName && !this.characterPromptMap.has(activeName)) {
            const fallbackId = String(activeId || activeName).trim();
            this.characterPromptMap.set(activeName, activePrompt || '');
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
            const found = Array.from(this.characterIdToNameMap.entries()).find(([, name]) => name === activeName);
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
}
