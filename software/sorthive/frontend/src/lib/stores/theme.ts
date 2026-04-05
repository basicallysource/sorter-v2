import { writable } from 'svelte/store';

export type Theme = 'light' | 'dark';

const STORAGE_KEY = 'sorthive.theme';

function preferredTheme(): Theme {
	if (typeof window === 'undefined') return 'light';
	const stored = window.localStorage.getItem(STORAGE_KEY);
	if (stored === 'light' || stored === 'dark') return stored;
	return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function createThemeStore() {
	const { subscribe, set } = writable<Theme>('light');

	return {
		subscribe,
		init() {
			set(preferredTheme());
		},
		setTheme(theme: Theme) {
			if (typeof window !== 'undefined') {
				window.localStorage.setItem(STORAGE_KEY, theme);
			}
			set(theme);
		},
		toggle(current: Theme) {
			this.setTheme(current === 'dark' ? 'light' : 'dark');
		}
	};
}

export const theme = createThemeStore();
