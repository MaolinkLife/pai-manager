import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { MatrixComponent } from './matrix.component';

describe('MatrixComponent: inner voice', () => {
    const response = (state: any, traces: any[]) => ({
        status: 'success',
        character: { id: 'c1', name: 'Test' },
        state,
        latest_snapshot: {},
        daily_summary: {},
        recent_traces: traces,
    });

    function create(payload: any): MatrixComponent {
        const moralStateService: any = { dashboard$: of(null), getState$: () => of(payload) };
        const localization: any = { init: () => undefined, currentLang: () => 'ru-RU' };
        const component = TestBed.runInInjectionContext(() => new MatrixComponent(moralStateService, localization));
        component.ngOnInit();
        return component;
    }

    it('shows the inner voice instead of the matrix analysis', () => {
        const voice = 'Мне тепло, потому что ты спросил так ласково.';
        const component = create(response(
            { current_emotion: 'tenderness', emotion_vector: {}, trigger: "The user's affectionate surprise.", inner_voice: voice },
            [{ primary_emotion: 'tenderness', cause: "The user's affectionate surprise.", notes: { inner_voice: voice } }],
        ));

        expect(component.innerVoice).toBe(voice);
        expect(component.latestTraceVoice).toBe(voice);
    });

    it('falls back to the matrix analysis when there is no inner voice', () => {
        const component = create(response(
            { current_emotion: 'joy', emotion_vector: {}, trigger: 'thanks' },
            [{ primary_emotion: 'joy', cause: 'thanks', notes: {} }],
        ));

        expect(component.innerVoice).toBe('');
        expect(component.affectiveTrigger).toBe('thanks');
        expect(component.latestTraceVoice).toBe('');
        expect(component.latestTraceCause).toBe('thanks');
    });
});
