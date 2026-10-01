// Light or dark, and the operator's primary color, applied to <html> the way
// the design system does it (software/sorter-design-system/src/lib/theme.svelte.ts,
// docs/color.md). The choices themselves live in this app's stores: the mode
// in $lib/stores/settings (this browser), the color on the machine
// ($lib/stores/themeColor.svelte).

export type Mode = 'light' | 'dark';

// The primary as text sits on a surface, on the canvas, or on its own tint
// over either (the side nav's current page). The hardest of those, per mode,
// from app.css: the canvas in light mode, the raised plane in dark mode.
const HARDEST_GROUND: Record<Mode, string> = { light: '#eceae5', dark: '#242422' };
const SOFT_SHARE: Record<Mode, number> = { light: 0.12, dark: 0.22 };
const INK = '#1b1a18';

export function applyMode(mode: Mode) {
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

function luminance(color: string): number {
	const [r, g, b] = rgb(color).map((c) => {
		const s = c / 255;
		return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
	});
	return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
	const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
	return (hi + 0.05) / (lo + 0.05);
}

/** White or ink, whichever reads better on a fill of this color: the text on
 *  the primary, or on a chip filled with a piece's LEGO color. */
export function onColor(fill: string): string {
	return contrast(fill, '#ffffff') >= contrast(fill, INK) ? '#ffffff' : INK;
}

/** The color, moved toward black (light mode) or white (dark mode) until it
 *  reaches 4.5:1 against the ground, so it can be used as text there. */
function readableOn(color: string, ground: string, mode: Mode): string {
	const toward = mode === 'light' ? '#000000' : '#ffffff';
	for (let t = 0; t <= 1; t += 0.02) {
		const moved = mix(color, toward, t);
		if (contrast(moved, ground) >= 4.5) return moved;
	}
	return toward;
}

// --- canvas charts ---

/** A token's value where `el` sits, for what a canvas draws: charts use the
 *  page's own colors (docs/components.md, Charts). */
export function token(name: string, el: Element = document.documentElement): string {
	return getComputedStyle(el).getPropertyValue(name).trim();
}

/** Chart labels: 12px in the page's typeface. */
export function chartFont(el: Element, weight = 400): string {
	return `${weight} 12px ${getComputedStyle(el).fontFamily}`;
}
