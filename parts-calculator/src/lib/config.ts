/**
 * Browser-persisted user configuration. The page mirrors its reactive state into
 * here on change and reloads it at boot, so a refresh keeps your build setup.
 */
import { browser } from '$app/environment';

export const CONFIG_KEY = 'sorter-filament-config-v1';

// Note: state shared across tabs lives in its own store, not here — layer
// configuration in layers.svelte.ts, filament colours in colors.svelte.ts.
// (`roleColors` was stored here until the assembly tab needed it too; that
// store still migrates the old key out of this blob.)
export type StoredConfig = {
	printBins: boolean;
	surplus: number;
	selected: Record<string, boolean>;
	inclSupport: Record<string, boolean>;
};

export function loadConfig(): Partial<StoredConfig> | null {
	if (!browser) return null;
	try {
		const raw = localStorage.getItem(CONFIG_KEY);
		return raw ? (JSON.parse(raw) as Partial<StoredConfig>) : null;
	} catch {
		return null;
	}
}

export function saveConfig(c: StoredConfig): void {
	if (!browser) return;
	try {
		localStorage.setItem(CONFIG_KEY, JSON.stringify(c));
	} catch {
		/* storage full / disabled — ignore */
	}
}

export function clearConfig(): void {
	if (!browser) return;
	try {
		localStorage.removeItem(CONFIG_KEY);
	} catch {
		/* ignore */
	}
}
