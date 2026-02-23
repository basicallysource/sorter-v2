import { writable } from 'svelte/store';

type Theme = 'light' | 'dark';

interface Settings {
	theme: Theme;
	debug: number;
}

const DEFAULT_SETTINGS: Settings = {
	theme: 'light',
	debug: 0
};

function createSettings() {
	const { subscribe, set, update } = writable<Settings>(DEFAULT_SETTINGS);

	return {
		subscribe,
		set,
		setTheme: (theme: Theme) => update((s) => ({ ...s, theme })),
		setDebug: (debug: number) => update((s) => ({ ...s, debug }))
	};
}

export const settings = createSettings();
