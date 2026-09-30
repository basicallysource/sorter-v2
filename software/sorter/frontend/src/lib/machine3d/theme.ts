// The page's colour tokens, read for the 3D view, which draws in them too.
import { Color } from 'three';
import type { Theme } from './view';

export function readTheme(): Theme {
	const css = getComputedStyle(document.documentElement);
	const token = (name: string) => css.getPropertyValue(name).trim();
	const dark = document.documentElement.classList.contains('dark');
	const surface = token('--surface');
	const primary = token('--primary');
	// The primary's tint (the token is a color-mix the canvas cannot read).
	const primarySoft = `#${new Color(surface).lerp(new Color(primary), dark ? 0.22 : 0.12).getHexString()}`;
	return {
		canvas: token('--canvas'),
		surface,
		well: token('--well'),
		ink: token('--ink'),
		inkMuted: token('--ink-muted'),
		primary,
		primarySoft,
		success: token('--success'),
		info: token('--info'),
		dark
	};
}
