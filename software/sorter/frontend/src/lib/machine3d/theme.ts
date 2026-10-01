// The page's colour tokens, read for the 3D view, which draws in them too.
import type { Theme } from './view';

export function readTheme(): Theme {
	const css = getComputedStyle(document.documentElement);
	const token = (name: string) => css.getPropertyValue(name).trim();
	return {
		canvas: token('--canvas'),
		surface: token('--surface'),
		ink: token('--ink'),
		primary: token('--primary'),
		success: token('--success'),
		dark: document.documentElement.classList.contains('dark')
	};
}
