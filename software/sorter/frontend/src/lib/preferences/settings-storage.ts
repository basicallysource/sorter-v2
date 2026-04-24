export type Theme = 'light' | 'dark';

export type Settings = {
	theme: Theme;
};

export const DEFAULT_SETTINGS: Settings = {
	theme: 'light'
};

const SETTINGS_STORAGE_KEY = 'settings';

function normalizeTheme(value: unknown): Theme {
	return value === 'dark' || value === 'light' ? value : DEFAULT_SETTINGS.theme;
}

export function normalizeSettings(value: unknown): Settings {
	const record = value && typeof value === 'object' ? (value as Partial<Settings>) : {};
	return {
		theme: normalizeTheme(record.theme)
	};
}

export function loadStoredSettings(): Settings | null {
	if (typeof window === 'undefined') return null;
	try {
		const stored = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
		if (!stored) return null;
		return normalizeSettings(JSON.parse(stored));
	} catch (e) {
		console.error(e);
		return null;
	}
}

export function persistStoredSettings(settings: Settings): void {
	if (typeof window === 'undefined') return;
	try {
		window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(normalizeSettings(settings)));
	} catch (e) {
		console.error(e);
	}
}

export function restoreStoredSettings(store: { set: (settings: Settings) => void }): void {
	const stored = loadStoredSettings();
	if (stored) store.set(stored);
}
