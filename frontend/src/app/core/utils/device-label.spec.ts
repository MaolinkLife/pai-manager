import { deviceLabel } from './device-label';

const WINDOWS_CHROME = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36';

describe('deviceLabel', () => {
    it('names the browser and the system', () => {
        expect(deviceLabel(WINDOWS_CHROME)).toBe('Chrome · Windows');
        expect(deviceLabel('Mozilla/5.0 (X11; Linux x86_64; rv:142.0) Gecko/20100101 Firefox/142.0')).toBe('Firefox · Linux');
        expect(deviceLabel(
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Safari/605.1.15',
        )).toBe('Safari · macOS');
    });

    it('tells the Chromium-based browsers apart from Chrome', () => {
        expect(deviceLabel(`${WINDOWS_CHROME} Edg/140.0.0.0`)).toBe('Edge · Windows');
        expect(deviceLabel(`${WINDOWS_CHROME} OPR/120.0.0.0`)).toBe('Opera · Windows');
        expect(deviceLabel(WINDOWS_CHROME.replace('Safari/537.36', 'YaBrowser/25.8.0.0 Safari/537.36'))).toBe('Yandex Browser · Windows');
    });

    it('knows a phone is not a desktop', () => {
        expect(deviceLabel(
            'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36',
        )).toBe('Chrome · Android');
        expect(deviceLabel(
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 Mobile/15E148 Safari/604.1',
        )).toBe('Safari · iOS');
        expect(deviceLabel(
            'Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/140.0.0.0 Mobile/15E148 Safari/604.1',
        )).toBe('Chrome · iOS');
    });

    it('gives what it knows and nothing for the unknown', () => {
        expect(deviceLabel('SomeClient (Windows NT 10.0)')).toBe('Windows');
        expect(deviceLabel('python-requests/2.31')).toBe('');
        expect(deviceLabel(null)).toBe('');
        expect(deviceLabel(undefined)).toBe('');
    });
});
