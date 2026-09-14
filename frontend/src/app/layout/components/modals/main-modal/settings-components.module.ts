import { CommonModule } from '@angular/common';
import { NgModule } from '@angular/core';
import { RouterModule } from '@angular/router';
import { SharedModule } from '../../../../shared/shared.module';
import { ModelCapabilityChipsComponent } from './shared/model-capability-chips/model-capability-chips.component';

import { LorebookComponent } from './lorebook/lorebook.component';
import { VoiceSettingsComponent } from './voice-settings/voice-settings.component';
import { AudioSettingsComponent } from './audio-settings/audio-settings.component';
import { VisionSettingsComponent } from './vision-settings/vision-settings.component';
import { RagSettingsComponent } from './rag-settings/rag-settings.component';
import { AnalyzerSettingsComponent } from './analyzer-settings/analyzer-settings.component';
import { MoralSettingsComponent } from './moral-settings/moral-settings.component';
import { GenerationSettingsComponent } from './generation-settings/generation-settings.component';
import { CoreSettingsComponent } from './core-settings/core-settings.component';
import { SystemSettingsComponent } from './system-settings/system-settings.component';
import { SocialSettingsComponent } from './social-settings/social-settings.component';
import { MediaSettingsComponent } from './media-settings/media-settings.component';
import { PersonaSettingsComponent } from './persona-settings/persona-settings.component';
import { ComplianceSettingsComponent } from './compliance-settings/compliance-settings.component';
import { InitiativeSettingsComponent } from './initiative-settings/initiative-settings.component';

const SETTINGS_COMPONENTS = [
    LorebookComponent,
    VoiceSettingsComponent,
    AudioSettingsComponent,
    VisionSettingsComponent,
    RagSettingsComponent,
    AnalyzerSettingsComponent,
    MoralSettingsComponent,
    GenerationSettingsComponent,
    CoreSettingsComponent,
    SystemSettingsComponent,
    SocialSettingsComponent,
    MediaSettingsComponent,
    PersonaSettingsComponent,
    ComplianceSettingsComponent,
    InitiativeSettingsComponent,
    ModelCapabilityChipsComponent,
];

/**
 * Settings group components shared between the legacy main-modal and the
 * /settings page. Declared here (instead of AppModule) so the lazy settings
 * feature can reuse them without duplicating declarations.
 */
@NgModule({
    declarations: SETTINGS_COMPONENTS,
    imports: [CommonModule, SharedModule, RouterModule],
    exports: SETTINGS_COMPONENTS,
})
export class SettingsComponentsModule {}
