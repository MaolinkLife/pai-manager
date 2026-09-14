import { UntypedFormBuilder } from '@angular/forms';
import { Observable, of, throwError } from 'rxjs';
import { PersonaSettingsComponent } from './persona-settings.component';

const preview = (overrides: Record<string, unknown> = {}) => ({
    status: 'ok',
    character: { id: 'kate', name: 'Kate' },
    counts: {
        history: 44,
        emotional_traces: 19,
        moral_state_snapshots: 19,
        daily_activity_diary: 2,
        conversation_state_logs: 3,
        forgiveness_events: 1,
    },
    has_data: true,
    files: 0,
    files_bytes: 0,
    library_files: 0,
    blocked: null,
    ...overrides,
});

describe('PersonaSettingsComponent character create and delete', () => {
    let created: string[];
    let deleted: string[];
    let errors: string[];
    let successes: string[];

    function create(options: { preview?: Observable<any>; deleteResult?: Observable<any>; createResult?: Observable<any> } = {}) {
        created = [];
        deleted = [];
        errors = [];
        successes = [];
        const configService: any = {
            createSystemCharacter$: (name: string) => {
                created.push(name);
                return options.createResult ?? of({ character: { id: name.toLowerCase(), name, prompt: '' } });
            },
            getCharacterDeletionPreview$: () => options.preview ?? of(preview()),
            deleteSystemCharacter$: (id: string) => {
                deleted.push(id);
                return options.deleteResult ?? of({
                    characters: [{ id: 'lim', name: 'Lim', prompt: 'Lim prompt' }],
                    active_character_id: 'lim',
                    active_char_name: 'Lim',
                    archive: { file_name: 'Kate_20260913-230000.zip' },
                });
            },
        };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const notifications: any = {
            success: (message: string) => successes.push(message),
            error: (message: string) => errors.push(message),
        };
        const component = new PersonaSettingsComponent(
            new UntypedFormBuilder(), configService, {} as any, localization, notifications,
        );
        component.personaForm.get('active_character_id')!.setValue('kate');
        return component;
    }

    it('opens with what goes into the archive', () => {
        const component = create();

        component.deleteSelectedCharacter();

        expect(component.showDeleteCharacterModal).toBeTrue();
        expect(component.deletePreviewLoading).toBeFalse();
        expect(component.deleteSummaryRows).toEqual([
            { labelKey: 'personaSettings.deleteCounts.history', count: 44 },
            { labelKey: 'personaSettings.deleteCounts.diary', count: 2 },
            { labelKey: 'personaSettings.deleteCounts.emotionalTraces', count: 19 },
            { labelKey: 'personaSettings.deleteCounts.moralSnapshots', count: 19 },
            { labelKey: 'personaSettings.deleteCounts.other', count: 4 },
        ]);
    });

    it('deletes only after the exact name is typed', () => {
        const component = create();
        component.deleteSelectedCharacter();

        expect(component.canConfirmDelete()).toBeFalse();
        component.deleteConfirmName = 'Kat';
        expect(component.canConfirmDelete()).toBeFalse();
        component.deleteConfirmName = 'Kate';
        expect(component.canConfirmDelete()).toBeTrue();

        component.confirmDeleteCharacter();

        expect(deleted).toEqual(['kate']);
        expect(component.isCharacterDeleteBusy).toBeFalse();
        expect(component.showDeleteCharacterModal).toBeFalse();
        expect(successes).toEqual(['personaSettings.deletedToArchive Kate_20260913-230000.zip']);
    });

    it('asks for the name also when there is no history', () => {
        const component = create({ preview: of(preview({ counts: {}, has_data: false })) });
        component.deleteSelectedCharacter();

        expect(component.deleteSummaryRows).toEqual([]);
        expect(component.canConfirmDelete()).toBeFalse();
        component.deleteConfirmName = 'Kate';
        expect(component.canConfirmDelete()).toBeTrue();
    });

    it('does not confirm a character with Telegram messages', () => {
        const component = create({
            preview: of(preview({ blocked: { code: 'telegram_messages', message: 'The character has Telegram messages.' } })),
        });
        component.deleteSelectedCharacter();
        component.deleteConfirmName = 'Kate';

        expect(component.deleteBlockedMessage).toBe('personaSettings.deleteBlockedTelegram');
        expect(component.canConfirmDelete()).toBeFalse();
        component.confirmDeleteCharacter();
        expect(deleted).toEqual([]);
    });

    it('releases the delete button after an error and keeps the dialog', () => {
        const component = create({
            deleteResult: throwError({ error: { detail: 'The character archive failed, nothing was deleted' } }),
        });
        component.deleteSelectedCharacter();
        component.deleteConfirmName = 'Kate';

        component.confirmDeleteCharacter();

        expect(component.isCharacterDeleteBusy).toBeFalse();
        expect(component.showDeleteCharacterModal).toBeTrue();
        expect(errors).toEqual(['The character archive failed, nothing was deleted']);
    });

    it('releases the create button after an error and keeps the typed name', () => {
        const component = create({
            createResult: throwError({ error: { detail: 'A character with this name already exists' } }),
        });
        component.openCreateCharacterModal();
        component.newCharacterName = 'Kate';

        component.createCharacter();

        expect(created).toEqual(['Kate']);
        expect(component.isCharacterCreateBusy).toBeFalse();
        expect(component.showCreateCharacterModal).toBeTrue();
        expect(component.newCharacterName).toBe('Kate');
        expect(errors).toEqual(['A character with this name already exists']);
    });

    it('closes the dialog with the reason when the preview fails', () => {
        const component = create({ preview: throwError({ error: { detail: 'Only the owner can do this' } }) });

        component.deleteSelectedCharacter();

        expect(component.showDeleteCharacterModal).toBeFalse();
        expect(component.deletePreviewLoading).toBeFalse();
        expect(errors).toEqual(['Only the owner can do this']);
    });
});

describe('PersonaSettingsComponent partial saves', () => {
    let saved: any[];

    function create(config$: Observable<any> = of({ synthesis: { prompting: { appearance_prompt: '' } }, telegram: { enabled: false } })) {
        saved = [];
        const configService: any = {
            getConfig$: () => config$,
            getSystem$: () => of({ system: { prompt: 'A prompt', active_character_id: 'c1', char_name: 'Test' } }),
            getSystemCharacters$: () => of({ characters: [{ id: 'c1', name: 'Test', prompt: 'A prompt' }], active_character_id: 'c1' }),
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
            invalidateConfig: () => undefined,
        };
        // Only what the tab reads on load; any other Telegram call fails the test instead of reaching a network.
        const telegramService: any = {
            listChats$: () => of({ chats: [{ chat_id: 101, title: 'Chat', chat_kind: 'private', username: '' }] }),
        };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const notifications: any = { success: () => undefined, error: () => undefined };
        const component = new PersonaSettingsComponent(
            new UntypedFormBuilder(), configService, telegramService, localization, notifications,
        );
        component.ngOnInit();
        return component;
    }

    it('has nothing to save right after loading', () => {
        const component = create();

        expect(component.hasChanges()).toBeFalse();
    });

    it('saves one appearance field without the rest of the image settings', () => {
        const component = create();

        component.personaForm.get('visual_profile.default_outfit')!.setValue('a grey coat');
        component.saveChanges();

        expect(saved).toEqual([{
            synthesis: {
                prompting: {
                    visual_profile: { default_outfit: 'a grey coat' },
                    per_character_visual_profiles: { Test: { default_outfit: 'a grey coat' } },
                },
            },
        }]);
    });

    it('saves a chat binding without the rest of the Telegram settings', () => {
        const component = create();

        component.chatBindingControls.at(0).get('character_id')!.setValue('c1');
        component.saveChanges();

        expect(saved).toEqual([{ telegram: { persona_bindings: { chat_character_map: { '101': 'c1' } } } }]);
    });

    it('does not save when the settings could not be loaded', () => {
        const component = create(throwError(() => new Error('offline')));

        component.personaForm.get('visual_profile.default_outfit')!.setValue('a grey coat');
        component.saveChanges();

        expect(component.hasChanges()).toBeFalse();
        expect(saved).toEqual([]);
    });
});
