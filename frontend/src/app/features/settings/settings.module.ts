import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { SharedModule } from '../../shared/shared.module';
import { SettingsComponentsModule } from '../../layout/components/modals/main-modal/settings-components.module';
import { SettingsRoutingModule } from './settings-routing.module';
import { SettingsComponent } from './settings.component';
import { ConnectionsSettingsComponent } from './components/connections-settings/connections-settings.component';
import { ModelsSettingsComponent } from './components/models-settings/models-settings.component';

@NgModule({
    declarations: [SettingsComponent, ConnectionsSettingsComponent, ModelsSettingsComponent],
    imports: [CommonModule, SharedModule, SettingsComponentsModule, SettingsRoutingModule],
})
export class SettingsModule {}
