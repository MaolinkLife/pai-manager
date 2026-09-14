import { TestBed } from '@angular/core/testing';
import { Subject, of } from 'rxjs';
import { ModelIndexEntry } from '../../../../core/services/api.service';
import { ModelCapabilitiesModalComponent } from './model-capabilities-modal/model-capabilities-modal.component';
import { ModelsSettingsComponent } from './models-settings.component';

const entry = (overrides: Partial<ModelIndexEntry> = {}): ModelIndexEntry => ({
    provider: 'ollama',
    name: 'llava:latest',
    capabilities: ['completion'],
    declared: ['completion'],
    declared_known: true,
    owner_marked: false,
    differs: false,
    ...overrides,
});

describe('ModelsSettingsComponent model capabilities', () => {
    let opened: Array<{ component: unknown; options: any }>;
    let closed: Subject<ModelIndexEntry | undefined>;

    function create(index: ModelIndexEntry[] = [entry()]) {
        opened = [];
        closed = new Subject<ModelIndexEntry | undefined>();
        const apiService: any = {
            getOllamaRuntimeModels$: () => of({ status: 'ok', models: [{ name: 'llava:latest', model: 'llava:latest', loaded: false }] }),
            getModelIndex$: () => of(index),
        };
        const modalService: any = {
            open: (component: unknown, options: any) => {
                opened.push({ component, options });
                return { afterClosed$: closed.asObservable() };
            },
        };
        const localization: any = { init: () => undefined, t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        // The component takes DestroyRef through inject(), so it is built in an injection context.
        const component = TestBed.runInInjectionContext(
            () => new ModelsSettingsComponent(apiService, { messages$: of() } as any, {} as any, localization, cdr, modalService),
        );
        component.refresh();
        return component;
    }

    it('shows what the index says each model can do', () => {
        const component = create();

        expect(component.indexByName['llava:latest'].capabilities).toEqual(['completion']);
    });

    it('opens the editor with the model and its entry', () => {
        const component = create();

        component.openCapabilities('llava:latest');

        expect(opened.length).toBe(1);
        expect(opened[0].component).toBe(ModelCapabilitiesModalComponent);
        expect(opened[0].options.title).toBe('llava:latest');
        expect(opened[0].options.appearance).toBe('default');
        expect(opened[0].options.data.entry).toEqual(entry());
        expect(opened[0].options.data.capabilityKeys).toEqual(component.capabilityKeys);
    });

    it('a saved entry replaces the row', () => {
        const component = create();
        component.openCapabilities('llava:latest');

        closed.next(entry({ capabilities: ['completion', 'vision'], owner_marked: true, differs: true }));

        expect(component.indexByName['llava:latest'].capabilities).toEqual(['completion', 'vision']);
        expect(component.indexByName['llava:latest'].differs).toBeTrue();
    });

    it('closing without saving keeps the row as it was', () => {
        const component = create();
        component.openCapabilities('llava:latest');

        closed.next(undefined);

        expect(component.indexByName['llava:latest']).toEqual(entry());
    });

    it('does not open an editor for a model the index does not know', () => {
        const component = create([]);

        component.openCapabilities('llava:latest');

        expect(opened).toEqual([]);
    });

    it('names what Ollama declares in the reminder', () => {
        const component = create();

        expect(component.differenceHint(entry({ declared: ['completion', 'tools'] })))
            .toBe('settingsPage.models.capabilitiesDifferHint settingsPage.models.capabilities.completion, settingsPage.models.capabilities.tools');
        expect(component.differenceHint(entry({ declared: [] })))
            .toBe('settingsPage.models.capabilitiesDifferHint settingsPage.models.capabilitiesNothingDeclared');
    });
});
