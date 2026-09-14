import { Component, Input } from '@angular/core';
import { MODEL_CAPABILITY_KEYS, ModelIndexEntry } from '../../../../../../core/services/api.service';

/** What a model can do, as read-only chips (model index). */
@Component({
    selector: 'app-model-capability-chips',
    templateUrl: './model-capability-chips.component.html',
    styleUrls: ['./model-capability-chips.component.less'],
})
export class ModelCapabilityChipsComponent {
    @Input() entry: ModelIndexEntry | null = null;

    readonly capabilityKeys = MODEL_CAPABILITY_KEYS;

    trackByKey(_index: number, key: string): string {
        return key;
    }
}
