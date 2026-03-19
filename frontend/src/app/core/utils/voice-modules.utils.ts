// utils/voice-modules.utils.ts
export const snakeToCamel = (str: string): string => {
    return str.replace(/_([a-z])/g, (g) => g[1].toUpperCase());
};

export const camelToSnake = (str: string): string => {
    return str.replace(/([A-Z])/g, '_$1').toLowerCase();
};

const deepMapKeys = (value: any, mapper: (key: string) => string): any => {
    if (Array.isArray(value)) {
        return value.map((item) => deepMapKeys(item, mapper));
    }

    if (value && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
        const mapped: any = {};
        Object.keys(value).forEach((key) => {
            mapped[mapper(key)] = deepMapKeys(value[key], mapper);
        });
        return mapped;
    }

    return value;
};

export const mapVoiceModulesDtoToModel = (voiceModulesDto: any): any => {
    if (!voiceModulesDto) return undefined;
    return deepMapKeys(voiceModulesDto, snakeToCamel);
};

export const mapVoiceModulesModelToDto = (voiceModulesModel: any): any => {
    if (!voiceModulesModel) return undefined;
    return deepMapKeys(voiceModulesModel, camelToSnake);
};
