/** Browser and system names recognised in a user agent, checked in order. */
const BROWSERS: [RegExp, string][] = [
    // Chromium-based browsers also carry "Chrome/", so they go first.
    [/Edg\//, 'Edge'],
    [/OPR\//, 'Opera'],
    [/YaBrowser\//, 'Yandex Browser'],
    [/Firefox\//, 'Firefox'],
    [/Chrome\/|CriOS\//, 'Chrome'],
    [/Version\/[\d.]+.*Safari\//, 'Safari'],
];

const SYSTEMS: [RegExp, string][] = [
    [/Windows/, 'Windows'],
    // Android carries "Linux" and iOS carries "Mac OS X", so both go before them.
    [/Android/, 'Android'],
    [/iPhone|iPad|iPod/, 'iOS'],
    [/Mac OS X|Macintosh/, 'macOS'],
    [/Linux|X11/, 'Linux'],
];

/** A short readable name for a signed-in device, like "Chrome · Windows"; empty when nothing is recognised. */
export function deviceLabel(userAgent: string | null | undefined): string {
    const agent = userAgent || '';
    const browser = BROWSERS.find(([pattern]) => pattern.test(agent))?.[1];
    const system = SYSTEMS.find(([pattern]) => pattern.test(agent))?.[1];
    return [browser, system].filter(Boolean).join(' · ');
}
