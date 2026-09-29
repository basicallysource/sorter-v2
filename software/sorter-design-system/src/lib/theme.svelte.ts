// Light or dark, and the operator's primary color (docs/color.md).
//
// The mode is a `dark` class on <html>; app.html sets it before first paint
// from the same storage key, so a dark page never flashes light. The primary
// is a CSS variable on <html>, with the two colors that depend on its
// contrast computed here: the text on a primary fill (white or ink), and
// the primary as text on a surface, darkened (or, in dark mode, lightened)
// until it reads.

import { DEFAULT_COLOR_ID, legoColor } from './lego-colors';

export type Mode = 'light' | 'dark';

const MODE_KEY = 'theme';
// The color's id, and its hex for app.html to paint before this module loads.
const COLOR_KEY = 'primary-id';
const PRIMARY_KEY = 'primary';

// The surfaces the primary is read against, per mode (app.css --color-surface).
const SURFACE: Record<Mode, string> = { light: '#ffffff', dark: '#1b1b19' };
const INK = '#1b1a18';

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
	const saved = read(MODE_KEY);
	if (saved === 'light' || saved === 'dark') return saved;
	return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

class Theme {
	mode = $state<Mode>(initialMode());
	colorId = $state(read(COLOR_KEY) ?? DEFAULT_COLOR_ID);
	primary = $derived(legoColor(this.colorId).hex);

	constructor() {
		$effect.root(() => {
			$effect(() => apply(this.mode, this.primary));
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

function apply(mode: Mode, primary: string) {
	const root = document.documentElement;
	root.classList.toggle('dark', mode === 'dark');
	root.style.setProperty('--color-primary', primary);
	root.style.setProperty('--color-on-primary', onColor(primary));
	root.style.setProperty('--color-primary-ink', readableOn(primary, SURFACE[mode], mode));
}

export const theme = new Theme();

// --- contrast (WCAG 2) ---

function rgb(hex: string): [number, number, number] {
	const h = hex.replace('#', '');
	const n = parseInt(
		h.length === 3
			? h
					.split('')
					.map((c) => c + c)
					.join('')
			: h,
		16
	);
	return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function hex([r, g, b]: [number, number, number]): string {
	return '#' + [r, g, b].map((c) => Math.round(c).toString(16).padStart(2, '0')).join('');
}

function luminance(color: string): number {
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
 *  reaches 4.5:1 against the surface, so it can be used as text there. */
export function readableOn(color: string, surface: string, mode: Mode): string {
	const target: [number, number, number] = mode === 'light' ? [0, 0, 0] : [255, 255, 255];
	const from = rgb(color);
	for (let t = 0; t <= 1; t += 0.04) {
		const mixed = hex([
			from[0] + (target[0] - from[0]) * t,
			from[1] + (target[1] - from[1]) * t,
			from[2] + (target[2] - from[2]) * t
		]);
		if (contrast(mixed, surface) >= 4.5) return mixed;
	}
	return hex(target);
}
