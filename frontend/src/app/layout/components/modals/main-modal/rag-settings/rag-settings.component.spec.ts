import { UntypedFormBuilder } from '@angular/forms';
import { of } from 'rxjs';
import { RagSettingsComponent } from './rag-settings.component';

describe('RagSettingsComponent memory save', () => {
    let updates: any[];

    function create() {
        updates = [];
        const configService: any = {
            updateConfig$: (body: any) => {
                updates.push(body);
                return of({});
            },
        };
        const cdr: any = { markForCheck: () => undefined, detectChanges: () => undefined };
        const localization: any = { t: (key: string) => key };
        const component = new RagSettingsComponent(new UntypedFormBuilder(), configService, {} as any, localization, cdr);
        const internals = component as any;
        internals.patchMemorySections({
            consolidation: { importanceThreshold: 0.2, judge: { enabled: false, provider: 'ollama', model: '', systemPrompt: 'judge' } },
            shortTerm: { startupRefreshEnabled: false, summarySystemPrompt: 'summarize', summaryTaskPrompt: 'what stayed' },
            diary: { narrative: { enabled: true, minChars: 80, maxChars: 3000 }, systemPrompt: 'diary', userTemplate: '{day}' },
        });
        internals.originalConfig = JSON.parse(JSON.stringify(internals.buildRagConfigFromForm()));
        internals.originalModules = internals.buildModulesPayload();
        return component;
    }

    it('shows the summaries-on-start switch as loaded', () => {
        const component = create();

        expect(component.ragForm.get('daySummaryStartupRefresh')!.value).toBeFalse();
    });

    it('sends only the summaries-on-start switch when it alone changed', () => {
        const component = create();
        component.ragForm.get('daySummaryStartupRefresh')!.setValue(true);

        component.saveChanges();

        expect(updates.length).toBe(1);
        expect(updates[0].memory).toEqual({ shortTerm: { startupRefreshEnabled: true } });
    });

    it('sends no memory when no memory field changed', () => {
        const component = create();

        component.saveChanges();

        expect(updates.every((body) => !('memory' in body))).toBeTrue();
    });

    it('does not send untouched stopwords', () => {
        const component = create();
        component.ragForm.get('daySummaryStartupRefresh')!.setValue(true);

        component.saveChanges();

        expect(updates).toEqual([{ memory: { shortTerm: { startupRefreshEnabled: true } } }]);
    });

    it('switching RAG sends only its own module flag', () => {
        const component = create();
        const internals = component as any;
        component.ragForm.get('enabled')!.setValue(false);
        internals.originalConfig = JSON.parse(JSON.stringify(internals.buildRagConfigFromForm()));
        internals.originalModules = {
            vtubeStudio: false, whisper: true, minecraft: false, gaming: false,
            alarm: false, discord: true, rag: false, visual: true,
        };

        component.ragForm.get('enabled')!.setValue(true);
        component.saveChanges();

        expect(updates.length).toBe(1);
        expect(updates[0].modules).toEqual({ rag: true });
    });

    it('sends edited stopwords as the whole list, and nothing else of retrieval', () => {
        const component = create();
        component.ragForm.get('retrievalKeywordStopwords')!.setValue('and, the');

        component.saveChanges();

        expect(updates).toEqual([{ rag: { retrieval: { keyword: { stopwords: ['and', 'the'] } } } }]);
    });
});
