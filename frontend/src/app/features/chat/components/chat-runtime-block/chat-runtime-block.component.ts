import { ChangeDetectionStrategy, Component, EventEmitter, Input, Output } from '@angular/core';
import { RuntimeStageView, RuntimeState } from '../../store';

@Component({
    selector: 'app-chat-runtime-block',
    templateUrl: './chat-runtime-block.component.html',
    styleUrls: ['./chat-runtime-block.component.less'],
    changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ChatRuntimeBlockComponent {
    @Input() runtime?: RuntimeState;
    @Input() summary = '';
    @Input() activeLabel = 'Обрабатываю запрос';
    @Input() stages: RuntimeStageView[] = [];

    @Output() toggleDetails = new EventEmitter<void>();
    @Output() skipThinking = new EventEmitter<void>();

    get isLive(): boolean {
        return this.runtime?.status === 'queued'
            || this.runtime?.status === 'running'
            || this.runtime?.status === 'started'
            || this.runtime?.status === 'stopping';
    }

    get canSkipThinking(): boolean {
        return this.isLive && this.activeLabel.toLowerCase().includes('размыш');
    }
}
