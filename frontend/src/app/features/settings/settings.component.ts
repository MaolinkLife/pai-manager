import { Component, OnInit } from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { LocalizationService } from '../../shared/pipes/translation/localization.service';

interface SettingsTab {
    key: string;
    labelKey: string;
}

interface SettingsGroup {
    labelKey: string;
    tabs: SettingsTab[];
}

const DEFAULT_TAB = 'connections';

@Component({
    selector: 'app-settings',
    templateUrl: './settings.component.html',
    styleUrls: ['./settings.component.less'],
})
export class SettingsComponent implements OnInit {
    readonly groups: SettingsGroup[] = [
        {
            labelKey: 'settingsPage.groups.system',
            tabs: [
                { key: 'connections', labelKey: 'settingsPage.tabs.connections' },
                { key: 'models', labelKey: 'settingsPage.tabs.models' },
                { key: 'generate', labelKey: 'settingsSidebar.generation' },
                { key: 'core', labelKey: 'settingsSidebar.core' },
                { key: 'system', labelKey: 'settingsSidebar.system' },
            ],
        },
        {
            labelKey: 'settingsPage.groups.intelligence',
            tabs: [
                { key: 'analyzer', labelKey: 'settingsSidebar.analyzer' },
                { key: 'compliance', labelKey: 'settingsSidebar.compliance' },
                { key: 'rag', labelKey: 'settingsSidebar.rag' },
            ],
        },
        {
            labelKey: 'settingsPage.groups.personality',
            tabs: [
                { key: 'persona', labelKey: 'settingsSidebar.persona' },
                { key: 'moral', labelKey: 'settingsSidebar.moral' },
                { key: 'lorebook', labelKey: 'settingsSidebar.lorebook' },
            ],
        },
        {
            labelKey: 'settingsPage.groups.perception',
            tabs: [
                { key: 'vision', labelKey: 'settingsSidebar.vision' },
                { key: 'audio', labelKey: 'settingsSidebar.audio' },
                { key: 'voice', labelKey: 'settingsSidebar.tts' },
            ],
        },
        {
            labelKey: 'settingsPage.groups.channels',
            tabs: [
                { key: 'media', labelKey: 'settingsSidebar.media' },
                { key: 'social', labelKey: 'settingsSidebar.social' },
            ],
        },
    ];

    activeTab = DEFAULT_TAB;

    private readonly knownTabs = new Set(
        this.groups.reduce<string[]>(
            (keys, group) => keys.concat(group.tabs.map((tab) => tab.key)),
            []
        )
    );

    constructor(
        private route: ActivatedRoute,
        private router: Router,
        private localizationService: LocalizationService,
    ) {}

    ngOnInit(): void {
        this.localizationService.init();
        this.route.paramMap.subscribe((params) => {
            const tab = params.get('tab') || DEFAULT_TAB;
            this.activeTab = this.knownTabs.has(tab) ? tab : DEFAULT_TAB;
        });
    }

    selectTab(key: string): void {
        this.router.navigate(['/settings', key]);
    }

    t(key: string): string {
        return this.localizationService.t(key);
    }
}
