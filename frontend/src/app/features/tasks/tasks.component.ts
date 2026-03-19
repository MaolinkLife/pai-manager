import { Component, OnInit } from '@angular/core';
import { UiFeatureFlagsService } from '../../core/services/ui-feature-flags.service';

@Component({
  selector: 'app-tasks',
  templateUrl: './tasks.component.html',
  styleUrls: ['./tasks.component.less']
})
export class TasksComponent implements OnInit {
    readonly featureEnabled: boolean;

  constructor(uiFeatureFlags: UiFeatureFlagsService) {
      this.featureEnabled = uiFeatureFlags.isEnabled('tasks');
  }

  ngOnInit(): void {
  }

}
