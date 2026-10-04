import { UntypedFormBuilder } from '@angular/forms';
import { Observable, of } from 'rxjs';
import { AnalyzerSettingsComponent } from './analyzer-settings.component';

describe('AnalyzerSettingsComponent: the analyzer prompt', () => {
    let saved: any[];
    let defaultsAsked: string[];

    const stored = () => ({
        analyzer: {
            enabled: true,
            activeProvider: 'ollama',
            fallbackOrder: [],
            releaseAfterUse: true,
            systemPrompt: 'Analyzer prompt.',
            providers: { ollama: { apiKey: '', model: 'qwen3.5:9b', temperature: 0.7, maxTokens: 1024 } },
        },
    });

    function create(
        config$: Observable<any> = of(stored()),
        defaults: Record<string, any> | null = { 'analyzer.system_prompt': 'Built-in analyzer prompt.' },
    ): AnalyzerSettingsComponent {
        saved = [];
        defaultsAsked = [];
        const configService: any = {
            getConfig$: () => config$,
            updateConfig$: (payload: any) => {
                saved.push(payload);
                return of({});
            },
            getDefaultValue$: (path: string) => {
                defaultsAsked.push(path);
                return of(defaults ? defaults[path] ?? null : null);
            },
        };
        const apiService: any = { getModelIndex$: () => of([]) };
        const notifications: any = { open: () => undefined };
        const cdr: any = { markForCheck: () => undefined };
        const localization: any = { t: (key: string) => key };
        const component = new AnalyzerSettingsComponent(
            new UntypedFormBuilder(), configService, apiService, notifications, cdr, localization,
        );
        component.ngOnInit();
        return component;
    }

    function withoutPrompt() {
        const config = stored();
        config.analyzer.systemPrompt = '';
        return of(config);
    }

    it('shows the stored analyzer prompt as it is, with nothing to save', () => {
        const component = create();

        expect(component.analyzerForm.get('systemPrompt')!.value).toBe('Analyzer prompt.');
        expect(defaultsAsked).toEqual([]);
        expect(component.hasChanges()).toBe(false);
    });

    it('shows the built-in analyzer prompt from the server when none is stored, with nothing to save', () => {
        const component = create(withoutPrompt());

        expect(defaultsAsked).toEqual(['analyzer.system_prompt']);
        expect(component.analyzerForm.get('systemPrompt')!.value).toBe('Built-in analyzer prompt.');
        expect(component.hasChanges()).toBe(false);
    });

    it('never puts a prompt of its own into the field', () => {
        const component = create(withoutPrompt(), null);

        expect(component.analyzerForm.get('systemPrompt')!.value).toBe('');
        component.analyzerForm.get('enabled')!.setValue(false);
        component.saveChanges();

        expect(saved).toEqual([{ analyzer: { enabled: false } }]);
    });
});
