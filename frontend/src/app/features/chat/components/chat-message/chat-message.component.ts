import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { UntypedFormControl } from '@angular/forms';
import { Message, MessageMedia } from '../../../../core/models/message.model';
import { RuntimeStageView } from '../../store';

export interface UsageDetailLine {
    key: string;
    value: string;
}

export interface ComplianceBadgeView {
    key: string;
    icon: string;
    label: string;
    state: 'ok' | 'warn';
    tooltip: string;
}

@Component({
    selector: 'app-chat-message',
    templateUrl: './chat-message.component.html',
    styleUrls: ['./chat-message.component.less'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatMessageComponent {
    @Input() msg!: Message;
    @Input() index = 0;
    @Input() charName = '';
    @Input() formattedTimestamp = '';
    @Input() messageSource?: Message['source'];
    @Input() isEditing = false;
    @Input() editMessageControl!: UntypedFormControl;
    @Input() loading = false;
    @Input() activeGenerationRunId: string | null = null;
    @Input() currentPlayingMessage: string | null = null;
    @Input() isLatestUserMessage = false;
    @Input() isLatestAssistantMessage = false;
    @Input() canContinue = false;
    @Input() hasRuntime = false;
    @Input() runtimeSummary = '';
    @Input() runtimeActiveLabel = '';
    @Input() runtimeStages: RuntimeStageView[] = [];
    @Input() renderContent = '';
    @Input() isStreaming = false;
    @Input() thinkingDurationMs?: number;
    @Input() collapseThinking = false;
    @Input() userContentExpandable = false;
    @Input() userContentExpanded = false;
    @Input() hasUsageMeta = false;
    @Input() usageOpen = false;
    @Input() usageLines: UsageDetailLine[] = [];

    @Output() toggleRuntimeDetails = new EventEmitter<Message>();
    @Output() saveEdit = new EventEmitter<Message>();
    @Output() cancelEdit = new EventEmitter<void>();
    @Output() previewMedia = new EventEmitter<MessageMedia>();
    @Output() downloadMedia = new EventEmitter<MessageMedia>();
    @Output() copy = new EventEmitter<Message>();
    @Output() edit = new EventEmitter<Message>();
    @Output() delete = new EventEmitter<Message>();
    @Output() toggleVoice = new EventEmitter<string>();
    @Output() reroll = new EventEmitter<string>();
    @Output() continueResponse = new EventEmitter<string>();
    @Output() activateVariant = new EventEmitter<string>();
    @Output() skipThinking = new EventEmitter<void>();
    @Output() toggleUsageDetails = new EventEmitter<{ message: Message; event: Event }>();
    @Output() toggleUserContent = new EventEmitter<string>();

    get actionsVisible(): boolean {
        return !this.msg.isPending;
    }

    /** Badge list for the compliance bar (assistant bubbles only).
     *  Empty array = bar hidden. Only checks that actually ran appear. */
    get complianceBadges(): ComplianceBadgeView[] {
        if (this.msg.role !== 'assistant' || !this.msg.compliance) {
            return [];
        }
        const c = this.msg.compliance;
        const badges: ComplianceBadgeView[] = [];

        if (c.validator?.compliance !== undefined) {
            const ok = c.validator.acceptable !== false;
            const pct = Math.round((c.validator.compliance ?? 0) * 100);
            const violations = (c.validator.violations || []).slice(0, 5).join('; ');
            badges.push({
                key: 'validator',
                icon: ok ? '✓' : '⚠',
                label: `${pct}%`,
                state: ok ? 'ok' : 'warn',
                tooltip: ok
                    ? `Validator: compliance ${pct}%`
                    : `Validator: compliance ${pct}% — ${violations || 'нарушения инструкций'}`,
            });
        }

        if (c.languageGuard?.ok !== undefined) {
            const ok = !!c.languageGuard.ok;
            badges.push({
                key: 'language',
                icon: '🌐',
                label: c.languageGuard.detected || '',
                state: ok ? 'ok' : 'warn',
                tooltip: ok
                    ? `Язык: ${c.languageGuard.detected} соответствует ${c.languageGuard.expected}`
                    : `Язык: ответ на ${c.languageGuard.detected}, ожидался ${c.languageGuard.expected}`,
            });
        }

        if (c.confidence?.score !== undefined) {
            const low = !!c.confidence.low;
            const pct = Math.round((c.confidence.score ?? 0) * 100);
            badges.push({
                key: 'confidence',
                icon: low ? '⚠' : '◎',
                label: `${pct}%`,
                state: low ? 'warn' : 'ok',
                tooltip: low
                    ? `Confidence: ${pct}% — ниже порога, ответ может быть неточным`
                    : `Confidence: ${pct}%`,
            });
        }

        if (c.factuality?.supported !== undefined) {
            const ok = !!c.factuality.supported;
            const claims = (c.factuality.claims || []).slice(0, 5).join('; ');
            badges.push({
                key: 'factuality',
                icon: ok ? '📚' : '❔',
                label: ok ? '' : 'unverified',
                state: ok ? 'ok' : 'warn',
                tooltip: ok
                    ? `Факты подтверждены памятью (${c.factuality.sourcesFound} источн.)`
                    : `Факты не найдены в памяти: ${claims || 'нет подтверждения'}`,
            });
        }

        return badges;
    }

    trackByBadge(_index: number, badge: ComplianceBadgeView): string {
        return badge.key;
    }

    get canSaveEdit(): boolean {
        return !(this.loading && !!this.activeGenerationRunId);
    }

    get canReroll(): boolean {
        return !(this.loading && !!this.activeGenerationRunId);
    }

    get hasVariants(): boolean {
        return this.msg.role === 'assistant' && Number(this.msg.variants?.count || 0) > 1;
    }

    get variantLabel(): string {
        const variants = this.msg.variants;
        if (!variants || variants.count <= 1) {
            return '';
        }
        return `${variants.active_index || this.msg.variant_index || 1}/${variants.count}`;
    }

    get previousVariantId(): string | null {
        return this.findSiblingVariant(-1);
    }

    get nextVariantId(): string | null {
        return this.findSiblingVariant(1);
    }

    private findSiblingVariant(direction: -1 | 1): string | null {
        const variants = this.msg.variants;
        if (!variants?.items?.length) {
            return null;
        }
        const activeIndex = variants.items.findIndex((item) => item.id === variants.active_id || item.active);
        if (activeIndex === -1) {
            return null;
        }
        const target = variants.items[activeIndex + direction];
        return target?.id || null;
    }

    trackByMedia(_index: number, media: MessageMedia): string {
        return media.id;
    }

    mediaSource(media: MessageMedia | null | undefined): string {
        if (!media) {
            return '';
        }
        if (media.dataUrl) {
            return media.dataUrl;
        }
        if (media.data) {
            return `data:${media.mimeType};base64,${media.data}`;
        }
        return media.url ?? '';
    }
}
