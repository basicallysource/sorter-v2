import { writable } from 'svelte/store';
import { DEFAULT_SETTINGS, type Settings, type Theme } from '$lib/preferences/settings-storage';

function createSettings() {
	const { subscribe, set, update } = writable<Settings>(DEFAULT_SETTINGS);

	return {
		subscribe,
		set,
		setTheme: (theme: Theme) => update((s) => ({ ...s, theme })),
		setContinuousMotionPanelEnabled: (enabled: boolean) =>
			update((s) => ({ ...s, continuousMotionPanelEnabled: Boolean(enabled) }))
	};
}

export const settings = createSettings();
