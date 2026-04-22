import { writable } from 'svelte/store';

type Theme = 'light' | 'dark';

interface Settings {
	theme: Theme;
}

const DEFAULT_SETTINGS: Settings = {
	theme: 'light'
};

function createSettings() {
	const { subscribe, set, update } = writable<Settings>(DEFAULT_SETTINGS);

	return {
		subscribe,
		set,
		setTheme: (theme: Theme) => update((s) => ({ ...s, theme }))
	};
}

export const settings = createSettings();
