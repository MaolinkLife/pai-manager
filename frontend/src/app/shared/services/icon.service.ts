import { HttpClient } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { ICON_REGISTRY } from '../icons/icon.registry';

@Injectable({ providedIn: 'root' })
export class IconService {
    private cache = new Map<string, string | null>();
    private inFlight = new Map<string, Promise<string | null>>();

    constructor(private http: HttpClient) { }

    async resolve(name: string, size = 16): Promise<string | null> {
        const rawName = (name || '').trim();
        if (!rawName) {
            return null;
        }

        const cacheKey = `${rawName}:${size}`;
        const cached = this.cache.get(cacheKey);
        if (cached !== undefined) {
            return cached;
        }

        const activeRequest = this.inFlight.get(cacheKey);
        if (activeRequest) {
            return activeRequest;
        }

        const request = this.load(rawName, size, cacheKey);
        this.inFlight.set(cacheKey, request);
        try {
            return await request;
        } finally {
            this.inFlight.delete(cacheKey);
        }
    }

    private async load(rawName: string, size: number, cacheKey: string): Promise<string | null> {
        const registryIcon = this.resolveFromRegistry(rawName, size);
        if (registryIcon) {
            this.cache.set(cacheKey, registryIcon);
            return registryIcon;
        }

        const candidates = rawName.startsWith('assets/') || rawName.startsWith('/assets/')
            ? this.buildPrefixedAssetCandidates(rawName, size)
            : this.buildDefaultAssetCandidates(rawName, size);

        for (const path of candidates) {
            try {
                const svg = await this.http.get(path, { responseType: 'text' }).toPromise();
                if (svg) {
                    this.cache.set(cacheKey, svg);
                    return svg;
                }
            } catch {
                // Continue through fallback candidates.
            }
        }

        this.cache.set(cacheKey, null);
        return null;
    }

    private resolveFromRegistry(rawName: string, size: number): string | null {
        if (rawName.startsWith('assets/') || rawName.startsWith('/assets/')) {
            return null;
        }

        const normalizedKey = this.toCamelCase(rawName);
        const capitalized = this.capitalize(normalizedKey);
        const internalIconKey = `icon${capitalized}`;
        const muiIconKey = `muiIcon${capitalized}`;

        const candidates = size >= 24
            ? [
                `${normalizedKey}Large`,
                normalizedKey,
                `${internalIconKey}Large`,
                internalIconKey,
                `${muiIconKey}Large`,
                muiIconKey,
            ]
            : [
                normalizedKey,
                `${normalizedKey}Large`,
                internalIconKey,
                `${internalIconKey}Large`,
                muiIconKey,
                `${muiIconKey}Large`,
            ];

        for (const key of candidates) {
            if (ICON_REGISTRY[key]) {
                return ICON_REGISTRY[key];
            }
        }

        return null;
    }

    private buildPrefixedAssetCandidates(path: string, size: number): string[] {
        const normalizedPath = path.startsWith('/') ? path : `/${path}`;
        const hasSvgExtension = normalizedPath.toLowerCase().endsWith('.svg');
        const basePath = hasSvgExtension ? normalizedPath.slice(0, -4) : normalizedPath;
        const candidates = [
            hasSvgExtension ? normalizedPath : `${basePath}.svg`,
            `${basePath}-${size}.svg`,
            `${basePath}-large.svg`,
        ];

        return Array.from(new Set(candidates));
    }

    private buildDefaultAssetCandidates(name: string, size: number): string[] {
        const kebabName = this.toKebabCase(name);
        const rawBase = `/assets/svg/${name}`;
        const kebabBase = `/assets/svg/${kebabName}`;
        const candidates = [
            `${rawBase}.svg`,
            `${rawBase}-${size}.svg`,
            `${rawBase}-large.svg`,
            `${kebabBase}.svg`,
            `${kebabBase}-${size}.svg`,
            `${kebabBase}-large.svg`,
        ];

        return Array.from(new Set(candidates));
    }

    private toCamelCase(value: string): string {
        const segments = value
            .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
            .split(/[^a-zA-Z0-9]+/)
            .filter(Boolean);

        if (!segments.length) {
            return '';
        }

        return segments
            .map((segment, index) => {
                const lower = segment.charAt(0).toLowerCase() + segment.slice(1);
                if (index === 0) {
                    return lower;
                }
                return lower.charAt(0).toUpperCase() + lower.slice(1);
            })
            .join('');
    }

    private toKebabCase(value: string): string {
        return value
            .replace(/([a-z0-9])([A-Z])/g, '$1-$2')
            .replace(/[\s_]+/g, '-')
            .replace(/[^a-zA-Z0-9-]/g, '-')
            .toLowerCase()
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '');
    }

    private capitalize(value: string): string {
        if (!value) {
            return value;
        }
        return value.charAt(0).toUpperCase() + value.slice(1);
    }
}
