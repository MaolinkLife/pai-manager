import { Component } from '@angular/core';
import { UiFeatureFlagsService } from '../../core/services/ui-feature-flags.service';

interface AuditInsight {
    text: string;
    level: 'info' | 'warn' | 'ok';
}

interface AuditRecord {
    timestamp: Date;
    score: number;
    summary: string;
    insights: AuditInsight[];
}

@Component({
    selector: 'app-audit',
    templateUrl: './audit.component.html',
    styleUrls: ['./audit.component.less'],
})
export class AuditComponent {
    readonly featureEnabled: boolean;
    isAuditing = false;

    records: AuditRecord[] = [
        {
            timestamp: new Date(Date.now() - 1000 * 60 * 25),
            score: 78,
            summary:
                'Стабильный диалог, хорошее удержание контекста и аккуратная реакция на смену темы. Есть редкие всплески длинных ответов.',
            insights: [
                { text: 'Context retention: high', level: 'ok' },
                { text: 'Latency spikes during reroll events', level: 'warn' },
                { text: 'Tone consistency: stable', level: 'ok' },
            ],
        },
        {
            timestamp: new Date(Date.now() - 1000 * 60 * 60 * 3),
            score: 72,
            summary:
                'Пайплайн в целом корректен, но есть несколько сообщений с неполным trace и разрывом между intent и generated response.',
            insights: [
                { text: 'Trace completeness: medium', level: 'info' },
                { text: 'One provider fallback occurred', level: 'warn' },
                { text: 'No critical regressions detected', level: 'ok' },
            ],
        },
    ];

    constructor(uiFeatureFlags: UiFeatureFlagsService) {
        this.featureEnabled = uiFeatureFlags.isEnabled('audit');
    }

    runAudit(): void {
        if (this.isAuditing) {
            return;
        }

        this.isAuditing = true;
        window.setTimeout(() => {
            this.records = [
                {
                    timestamp: new Date(),
                    score: 81,
                    summary:
                        'Свежий прогон: логика маршрутизации стабильна, память отрабатывает штатно, визуальные компоненты синхронизированы.',
                    insights: [
                        { text: 'Pipeline health: stable', level: 'ok' },
                        { text: 'UI consistency improved in side panels', level: 'ok' },
                        { text: 'Minor style drift in legacy settings', level: 'info' },
                    ],
                },
                ...this.records,
            ];
            this.isAuditing = false;
        }, 1200);
    }
}
