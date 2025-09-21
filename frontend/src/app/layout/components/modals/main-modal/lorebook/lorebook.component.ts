// lorebook.component.ts
import { Component, OnInit } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { LorebookEntry } from '../../../../../core/models/lorebook-entry.model';
import { LorebookService } from '../../../../../core/services/lorebook.service';

@Component({
    selector: 'app-lorebook',
    templateUrl: './lorebook.component.html',
    styleUrls: ['./lorebook.component.less']
})
export class LorebookComponent implements OnInit {

    entries$: BehaviorSubject<LorebookEntry[]> = new BehaviorSubject<LorebookEntry[]>([]);

    constructor(private lorebookService: LorebookService) { }

    ngOnInit(): void {
        this.loadEntries();
    }

    loadEntries(): void {
        this.lorebookService.getLorebook$().subscribe(
            entries => {
                this.entries$.next(entries);
            },
            error => {
                console.error('Ошибка загрузки записей:', error);
            }
        );
    }

    clickDelete(entry: LorebookEntry): void {
        if (entry.id && confirm('Вы уверены, что хотите удалить эту запись?')) {
            this.lorebookService.deleteEntry$(entry.id).subscribe(
                () => {
                    this.loadEntries(); // Перезагружаем список
                },
                error => {
                    console.error('Ошибка удаления записи:', error);
                }
            );
        }
    }

    save(): void {
        // Сохраняем все изменения
        const entries = this.entries$.getValue();

        // Здесь можно добавить логику сохранения
        // Пока просто показываем в консоли
        console.log('Сохраняем записи:', entries);

        // Для примера - добавим новую запись
        this.addNewEntry();
    }

    addNewEntry(): void {
        const newEntry: LorebookEntry = {
            content: '',
            keywords: '',
            category: 'general',
            active: true
        };

        this.lorebookService.createEntry$(newEntry).subscribe(
            response => {
                this.loadEntries(); // Перезагружаем список
            },
            error => {
                console.error('Ошибка создания записи:', error);
            }
        );
    }

    updateEntry(entry: LorebookEntry): void {
        if (entry.id) {
            this.lorebookService.updateEntry$(entry.id, entry).subscribe(
                response => {
                    console.log('Запись обновлена:', response);
                },
                error => {
                    console.error('Ошибка обновления записи:', error);
                }
            );
        }
    }
}
