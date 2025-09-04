import { Component, OnInit } from '@angular/core';
import { ModalService } from '../shared/components/modal/modal.service';
import { MemoryModalComponent } from './components/modals/memory-modal/memory-modal.component';
import { MOCK_LOREBOOK } from '../shared/mock/lorebook-mock';
import { MainModalComponent } from './components/modals/main-modal/main-modal.component';

@Component({
    selector: 'app-layout',
    templateUrl: './layout.component.html',
    styleUrls: ['./layout.component.less']
})
export class LayoutComponent implements OnInit {
    constructor(private modalService: ModalService) { }

    ngOnInit(): void { }

    memoryClick() {
        this.modalService.open(MainModalComponent, {
            title: 'Settings',
            data: { entries: MOCK_LOREBOOK }
        }).afterClosed$.subscribe(updated => {
            console.log('Сохранено:', updated);
        });

    }
}

