import { LEGO_COLORS, type LegoColor } from '$lib/lego-colors';
import { onColor } from '$lib/theme';
import { currentPalette, setCurrentPalette } from './palette.svelte';

// The BrickLink palette a piece's true color is picked from, served by GET
// /api/pieces/colors (Hive's, or the machine's saved copy). Cached per backend
// base so it is fetched once per machine per session; an empty answer (the
// machine has never reached Hive) is not cached, so the next open asks again.

export type BrickLinkColor = {
	id: number;
	name: string;
	rgb: string | null; // hex WITHOUT a leading '#', e.g. "05131D"
	is_trans: boolean;
};

type ColorsResponse = { results: BrickLinkColor[] };

const cache = new Map<string, BrickLinkColor[]>();
const inflight = new Map<string, Promise<BrickLinkColor[]>>();

export async function fetchLegoColors(base: string): Promise<BrickLinkColor[]> {
	const cached = cache.get(base);
	if (cached) return cached;
	const pending = inflight.get(base);
	if (pending) return pending;

	const p = (async () => {
		const res = await fetch(`${base}/api/pieces/colors`);
		if (!res.ok) throw new Error(`colors ${res.status}`);
		const json = (await res.json()) as ColorsResponse;
		const results = Array.isArray(json?.results) ? json.results : [];
		if (results.length > 0) {
			cache.set(base, results);
			setCurrentPalette(results);
		}
		return results;
	})();
	inflight.set(base, p);
	try {
		return await p;
	} finally {
		inflight.delete(base);
	}
}

// A '#'-prefixed CSS color for a swatch, or null when the palette entry has no
// rgb (some BrickLink colors carry no canonical hex).
export function swatchHex(rgb: string | null | undefined): string | null {
	if (!rgb) return null;
	const trimmed = rgb.replace(/^#/, '');
	return /^[0-9a-fA-F]{6}$/.test(trimmed) ? `#${trimmed}` : null;
}

// Readable text on a swatch: white or ink, by contrast.
export function swatchTextColor(rgb: string | null | undefined): string {
	const hex = swatchHex(rgb);
	return hex ? onColor(hex) : onColor('#ffffff');
}

// A piece's color as a name and a swatch. Pieces carry BrickLink color ids
// ("11"), so the BrickLink palette (once loaded) answers by id, for every
// color; before it loads, or for a name alone, the operator palette answers
// by name. Null when neither knows it.
export function findLegoColor(
	color_id: string | null | undefined,
	color_name: string | null | undefined
): LegoColor | null {
	const palette = currentPalette();
	if (color_id && /^\d+$/.test(color_id)) {
		const bl = palette.find((c) => String(c.id) === color_id);
		const hex = swatchHex(bl?.rgb);
		if (bl && hex) return { id: color_id, name: bl.name, hex };
	}
	if (color_name) {
		const lower = color_name.toLowerCase();
		const bl = palette.find((c) => c.name.toLowerCase() === lower);
		const hex = swatchHex(bl?.rgb);
		if (bl && hex) return { id: String(bl.id), name: bl.name, hex };
		const by_name = LEGO_COLORS.find((c) => c.name.toLowerCase() === lower);
		if (by_name) return by_name;
	}
	return null;
}
