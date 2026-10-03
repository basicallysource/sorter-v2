// Light or dark, and the operator's primary color (docs/color.md).
//
// The mode is a `dark` class on <html>; app.html sets it before first paint
// from the same storage key, so a dark page never flashes light. The primary
// is --primary on <html>, with the colors that depend on its contrast worked
// out here rather than listed per color: the text on a primary fill (white or
// ink), and the primary as text, darkened for light mode and lightened for
// dark mode until it reads on the backgrounds it is used on.
//
// It is safe to import where pages render on the server (Hive): there it
// reads nothing and keeps the defaults, and in the browser the pre-paint
// script and this module put the stored choices in place.

import { DEFAULT_COLOR_ID, legoColor } from './lego-colors';

export type Mode = 'light' | 'dark';

const MODE_KEY = 'theme';
// The color's id, and its hex for app.html to paint before this module loads.
const COLOR_KEY = 'primary-id';
const PRIMARY_KEY = 'primary';

// The primary as text sits on a surface, on the canvas, or on its own tint
// over either (the side nav's current page). The hardest of those, per mode,
// from app.css: the canvas in light mode, the raised plane in dark mode.
const HARDEST_GROUND: Record<Mode, string> = { light: '#eceae5', dark: '#242422' };
const SOFT_SHARE: Record<Mode, number> = { light: 0.12, dark: 0.22 };
const INK = '#1b1a18';

const browser = typeof window !== 'undefined';

function read(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

function write(key: string, value: string) {
	try {
		localStorage.setItem(key, value);
	} catch {
		// Storage can be off (a private window); the choice lasts the visit.
	}
}

function initialMode(): Mode {
	if (!browser) return 'light';
	const saved = read(MODE_KEY);
	if (saved === 'light' || saved === 'dark') return saved;
	return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

class Theme {
	mode = $state<Mode>(initialMode());
	colorId = $state(read(COLOR_KEY) ?? DEFAULT_COLOR_ID);
	primary = $derived(legoColor(this.colorId).hex);

	constructor() {
		if (!browser) return;
		$effect.root(() => {
			$effect(() => applyMode(this.mode));
			$effect(() => applyPrimary(this.primary));
		});
	}

	setMode(mode: Mode) {
		this.mode = mode;
		write(MODE_KEY, mode);
	}

	setColor(id: string) {
		this.colorId = legoColor(id).id;
		write(COLOR_KEY, this.colorId);
		write(PRIMARY_KEY, this.primary);
	}
}

function applyMode(mode: Mode) {
	document.documentElement.classList.toggle('dark', mode === 'dark');
}

/** Sets the primary on <html>, with the text colors worked out for both
 *  modes, so a light or dark subtree reads right whatever the page's mode. */
export function applyPrimary(primary: string, root: HTMLElement = document.documentElement) {
	root.style.setProperty('--primary', primary);
	root.style.setProperty('--on-primary', onColor(primary));
	for (const mode of ['light', 'dark'] as const) {
		const ground = mix(HARDEST_GROUND[mode], primary, SOFT_SHARE[mode]);
		root.style.setProperty(`--primary-ink-${mode}`, readableOn(primary, ground, mode));
	}
}

export const theme = new Theme();

// --- contrast (WCAG 2) ---

type Rgb = [number, number, number];

function rgb(hex: string): Rgb {
	const h = hex.replace('#', '');
	const full =
		h.length === 3
			? h
					.split('')
					.map((c) => c + c)
					.join('')
			: h;
	const n = parseInt(full, 16);
	return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function hex([r, g, b]: Rgb): string {
	return '#' + [r, g, b].map((c) => Math.round(c).toString(16).padStart(2, '0')).join('');
}

/** `share` of `over` laid on `under`, as a translucent fill would be. */
function mix(under: string, over: string, share: number): string {
	const a = rgb(under);
	const b = rgb(over);
	return hex([0, 1, 2].map((i) => a[i] + (b[i] - a[i]) * share) as Rgb);
}

export function luminance(color: string): number {
	const [r, g, b] = rgb(color).map((c) => {
		const s = c / 255;
		return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a: string, b: string): number {
	const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
}

/** White or ink, whichever reads better on a fill of this color. */
export function onColor(fill: string): string {
	return contrast(fill, '#ffffff') >= contrast(fill, INK) ? '#ffffff' : INK;
}

/** The color, moved toward black (light mode) or white (dark mode) until it
 *  reaches 4.5:1 against the ground, so it can be used as text there. */
export function readableOn(color: string, ground: string, mode: Mode): string {
	const toward = mode === 'light' ? '#000000' : '#ffffff';
	for (let t = 0; t <= 1; t += 0.02) {
		const moved = mix(color, toward, t);
		if (contrast(moved, ground) >= 4.5) return moved;
	}
	return toward;
}
