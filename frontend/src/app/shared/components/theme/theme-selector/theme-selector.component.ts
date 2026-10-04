import { Component } from '@angular/core';

@Component({
    selector: 'app-theme-selector',
    templateUrl: './theme-selector.component.html',
    styleUrls: ['./theme-selector.component.less'],
    standalone: false
})
export class ThemeSelectorComponent {
    themes = ['mui', 'lim', 'anomaly'];
    currentTheme = 'lim';

    switchTheme(theme: string) {
        this.currentTheme = theme;
        document.documentElement.setAttribute('data-theme', theme);
    }
}
