import { Subject, of } from 'rxjs';
import { MoralStateService } from './moral-state.service';

describe('MoralStateService: inner voice', () => {
    it('takes the inner voice from a live matrix event', () => {
        const messages$ = new Subject<string>();
        const service = new MoralStateService({} as any, { messages$ } as any);
        let state: any = null;
        service.state$.subscribe((value) => (state = value));

        messages$.next(JSON.stringify({
            type: 'moral_state',
            state: { current_emotion: 'tenderness', meta: { inner_voice: 'Мне тепло.' } },
        }));

        expect(state?.inner_voice).toBe('Мне тепло.');
    });

    it('keeps the inner voice the state route sends', () => {
        const http: any = { get: () => of({ state: { current_emotion: 'joy', inner_voice: 'Мне радостно.' } }) };
        const service = new MoralStateService(http, { messages$: new Subject<string>() } as any);
        let state: any = null;
        service.state$.subscribe((value) => (state = value));

        service.getState$().subscribe();

        expect(state?.inner_voice).toBe('Мне радостно.');
    });
});
