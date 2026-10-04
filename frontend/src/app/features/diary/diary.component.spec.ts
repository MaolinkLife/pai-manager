import { Observable, of, Subject } from 'rxjs';
import { DiaryComponent } from './diary.component';

const row = (day: string, pruned?: Record<string, unknown>) => ({
    id: day,
    character_id: 'char',
    day,
    mood: 'calm',
    summary: day,
    tags: [],
    stats: {},
    payload: pruned ? { pruned } : {},
    created_at: '',
    updated_at: '',
});

const rows = (from: number, count: number) =>
    Array.from({ length: count }, (_, index) => row(`day-${from + index}`));

describe('DiaryComponent', () => {
    let calls: Array<{ offset: number; limit: number; includeHidden: boolean }>;

    function create(respond: (offset: number, includeHidden: boolean) => Observable<any>): DiaryComponent {
        calls = [];
        const diaryService: any = {
            getEntries$: (offset: number, limit: number, includeHidden: boolean) => {
                calls.push({ offset, limit, includeHidden });
                return respond(offset, includeHidden);
            },
            generateEntry$: () => of({}),
        };
        const flags: any = { isEnabled: () => true };
        const component = new DiaryComponent(flags, diaryService);
        component.ngOnInit();
        return component;
    }

    it('asks for the first page of visible entries', () => {
        const component = create(() => of({ entries: rows(0, 30), has_more: true }));

        expect(calls).toEqual([{ offset: 0, limit: 30, includeHidden: false }]);
        expect(component.entries.length).toBe(30);
        expect(component.hasMore).toBe(true);
    });

    it('show more appends the next page from where the list ends', () => {
        const component = create((offset) =>
            of(offset === 0 ? { entries: rows(0, 30), has_more: true } : { entries: rows(30, 5), has_more: false }),
        );

        component.loadMore();

        expect(calls[1]).toEqual({ offset: 30, limit: 30, includeHidden: false });
        expect(component.entries.map((entry) => entry.summary)).toEqual(rows(0, 35).map((item) => item.summary));
        expect(component.hasMore).toBe(false);

        component.loadMore();
        expect(calls.length).toBe(2);
    });

    it('has nothing more to show when the first page is everything', () => {
        const component = create(() => of({ entries: rows(0, 4), has_more: false }));

        expect(component.hasMore).toBe(false);
    });

    it('shows hidden entries on request, marked with the reason', () => {
        const component = create((_offset, includeHidden) =>
            of({
                entries: includeHidden
                    ? [row('day-1'), row('day-2', { reason: 'low_importance', score: 0.1 })]
                    : [row('day-1')],
                has_more: false,
            }),
        );

        component.setShowHidden(true);

        expect(calls[1]).toEqual({ offset: 0, limit: 30, includeHidden: true });
        expect(component.entries.map((entry) => entry.hidden)).toEqual([false, true]);
        expect(component.entries[1].hiddenReason).toBe('low_importance');
        expect(component.hiddenReasonKey('low_importance')).toBe('diary.hiddenReasons.low_importance');
        expect(component.hiddenReasonKey('something_new')).toBeNull();

        component.setShowHidden(false);

        expect(calls[2]).toEqual({ offset: 0, limit: 30, includeHidden: false });
        expect(component.entries.length).toBe(1);
    });

    it('drops a page that arrives after the hidden switch', () => {
        const late = new Subject<any>();
        const component = create((offset) =>
            offset === 0 ? of({ entries: rows(0, 30), has_more: true }) : late,
        );

        component.loadMore();
        component.setShowHidden(true);
        late.next({ entries: [row('late')], has_more: false });

        expect(component.entries.map((entry) => entry.summary)).not.toContain('late');
        expect(component.entries.length).toBe(30);
    });
});
