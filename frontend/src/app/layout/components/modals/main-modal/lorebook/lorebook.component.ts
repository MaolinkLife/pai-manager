import { Component, OnInit, Output } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { LorebookEntry } from '../../../../../core/models/lorebook-entry.model';
import { ModalRef } from '../../../../../shared/components/modal/modal-ref';
import { MOCK_LOREBOOK } from '../../../../../shared/mock/lorebook-mock';
import { LorebookService } from '../../../../../core/services/lorebook.service';

@Component({
    selector: 'app-lorebook',
    templateUrl: './lorebook.component.html',
    styleUrls: ['./lorebook.component.less']
})
export class LorebookComponent implements OnInit {

    @Output() save: () => void = () => { };

    entries: LorebookEntry[] = [];

    mock = MOCK_LOREBOOK;

    entries$: BehaviorSubject<LorebookEntry[]> = new BehaviorSubject<LorebookEntry[]>([]);

    constructor(private lorebookService: LorebookService) { }

    ngOnInit(): void {
        this.entries$.next([...MOCK_LOREBOOK]);

        this.lorebookService.getLorebook$().subscribe(r => {
            console.log({
                r
            });

        })
    }

    clickDelete(entry: LorebookEntry): void {
        console.log({
            entry
        });

    }
}

