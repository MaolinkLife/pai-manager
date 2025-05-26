import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class ThemeService {
    switchTheme(theme: string) {
        document.documentElement.setAttribute('data-theme', theme);
    }
}
