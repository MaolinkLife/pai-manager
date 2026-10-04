import { UntypedFormBuilder } from '@angular/forms';
import { Observable, of } from 'rxjs';
import { ModelIndexEntry } from '../../../../../core/services/api.service';
import { ModelCapabilitiesModalComponent } from './model-capabilities-modal.component';

const KEYS = ['completion', 'vision', 'tools', 'thinking', 'embedding', 'insert'];

const entry = (overrides: Partial<ModelIndexEntry> = {}): ModelIndexEntry => ({
    provider: 'ollama',
    name: 'qwen3-embedding:latest',
    capabilities: ['embedding', 'tools'],
    declared: ['embedding', 'tools'],
    declared_known: true,
    owner_marked: false,
    differs: false,
    ...overrides,
});

describe('ModelCapabilitiesModalComponent', () => {
    let saved: Array<{ name: string; capabilities: string[] | null; provider: string }>;
    let closedWith: Array<ModelIndexEntry | null>;

    function create(model: ModelIndexEntry = entry(), saveResult?: Observable<ModelIndexEntry | null>) {
        saved = [];
        closedWith = [];
        const apiService: any = {
            setModelCapabilities$: (name: string, capabilities: string[] | null, provider: string) => {
                saved.push({ name, capabilities, provider });
                return saveResult ?? of({ ...model, capabilities: capabilities ?? model.declared, owner_marked: true, differs: true });
            },
        };
        const modalRef: any = { closeModal: (result?: ModelIndexEntry) => closedWith.push(result ?? null) };
        const localization: any = { t: (key: string) => key };
        const cdr: any = { markForCheck: () => undefined };
        const component = new ModelCapabilitiesModalComponent(new UntypedFormBuilder(), apiService, localization, modalRef, cdr);
        component.entry = model;
        component.capabilityKeys = KEYS;
        component.ngOnInit();
        return component;
    }

    it('ticks what the model can do', () => {
        const component = create();

        expect(component.selected()).toEqual(['tools', 'embedding']);
        expect(component.isDeclared('tools')).toBe(true);
        expect(component.differsFromOllama()).toBe(false);
    });

    it('saves the ticks and closes with the updated entry', () => {
        const component = create();
        component.form.get('tools')!.setValue(false);

        expect(component.differsFromOllama()).toBe(true);
        component.save();

        expect(saved).toEqual([{ name: 'qwen3-embedding:latest', capabilities: ['embedding'], provider: 'ollama' }]);
        expect(closedWith.length).toBe(1);
        expect(closedWith[0]!.capabilities).toEqual(['embedding']);
        expect(component.saving).toBe(false);
    });

    it('"As Ollama says" puts back the declared ticks without saving', () => {
        const component = create(entry({ capabilities: ['embedding'], owner_marked: true, differs: true }));

        component.resetToOllama();

        expect(component.selected()).toEqual(['tools', 'embedding']);
        expect(component.differsFromOllama()).toBe(false);
        expect(saved).toEqual([]);
    });

    it('a failed save keeps the editor open and says why', () => {
        const component = create(entry(), of(null));

        component.save();

        expect(closedWith).toEqual([]);
        expect(component.saving).toBe(false);
        expect(component.saveError).toBe('settingsPage.models.capabilitiesSaveError');
    });

    it('cancel closes without a result', () => {
        const component = create();

        component.cancel();

        expect(closedWith).toEqual([null]);
    });
});
