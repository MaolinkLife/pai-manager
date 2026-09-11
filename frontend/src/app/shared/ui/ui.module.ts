import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { CustomSvgModule } from '../components/custom-svg/custom-svg.module';
import { UiButtonComponent } from './components/ui-button/ui-button.component';
import { UiCheckboxComponent } from './components/ui-checkbox/ui-checkbox.component';
import { UiDropdownMenuDirective } from './components/ui-dropdown/directives/ui-dropdown-menu.directive';
import { UiDropdownTriggerDirective } from './components/ui-dropdown/directives/ui-dropdown-trigger.directive';
import { UiDropdownComponent } from './components/ui-dropdown/ui-dropdown.component';
import { UiInputComponent } from './components/ui-input/ui-input.component';
import { UiInputDateTimeComponent } from './components/ui-input-date-time/ui-input-date-time.component';
import { UiMultiselectComponent } from './components/ui-multiselect/ui-multiselect.component';
import { UiRangeComponent } from './components/ui-range/ui-range.component';
import { UiSelectComponent } from './components/ui-select/ui-select.component';
import { UiTabComponent } from './components/ui-tabs/ui-tab.component';
import { UiTabsComponent } from './components/ui-tabs/ui-tabs.component';
import { UiTextareaComponent } from './components/ui-textarea/ui-textarea.component';

@NgModule({
    declarations: [
        UiButtonComponent,
        UiCheckboxComponent,
        UiInputComponent,
        UiInputDateTimeComponent,
        UiRangeComponent,
        UiSelectComponent,
        UiTextareaComponent,
        UiMultiselectComponent,
        UiDropdownComponent,
        UiDropdownTriggerDirective,
        UiDropdownMenuDirective,
        UiTabsComponent,
        UiTabComponent,
    ],
    imports: [CommonModule, FormsModule, CustomSvgModule],
    exports: [
        UiButtonComponent,
        UiCheckboxComponent,
        UiInputComponent,
        UiInputDateTimeComponent,
        UiRangeComponent,
        UiSelectComponent,
        UiTextareaComponent,
        UiMultiselectComponent,
        UiDropdownComponent,
        UiDropdownTriggerDirective,
        UiDropdownMenuDirective,
        UiTabsComponent,
        UiTabComponent,
    ],
})
export class UiModule {}
