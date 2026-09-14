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
});
