import { Component } from '@angular/core';
import { UiFeatureFlagsService } from '../../core/services/ui-feature-flags.service';

interface DiaryEntry {
    date: string;
    mood: string;
    content: string;
    tags: string[];
}

@Component({
    selector: 'app-diary',
    templateUrl: './diary.component.html',
    styleUrls: ['./diary.component.less'],
})
export class DiaryComponent {
    readonly featureEnabled: boolean;

    entries: DiaryEntry[] = [
        {
            date: new Date().toISOString(),
            mood: 'Curious',
            content:
                'Сегодня я анализировала диалог и заметила, что чаще всего возвращаюсь к темам творчества, памяти и личных целей.',
            tags: ['session', 'mood', 'reflection'],
        },
        {
            date: new Date(Date.now() - 86400000).toISOString(),
            mood: 'Focused',
            content:
                'Отмечаю повторяющиеся намерения пользователя: улучшение UI, стабильный пайплайн и более глубокая работа памяти.',
            tags: ['ui', 'pipeline', 'memory'],
        },
    ];

    constructor(uiFeatureFlags: UiFeatureFlagsService) {
        this.featureEnabled = uiFeatureFlags.isEnabled('diary');
    }

    addMockEntry(): void {
        const now = new Date();
        this.entries = [
            {
                date: now.toISOString(),
                mood: 'Inspired',
                content:
                    'Черновая запись дневника создана в UI-режиме. Бэкенд-процесс генерации дневника пока не подключен.',
                tags: ['draft', 'frontend-only'],
            },
            ...this.entries,
        ];
    }
}
