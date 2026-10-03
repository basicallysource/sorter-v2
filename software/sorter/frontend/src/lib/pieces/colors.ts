import { LEGO_COLORS, type LegoColor } from '$lib/lego-colors';
import { onColor } from '$lib/theme';

// The full BrickLink LEGO color palette, served by GET /api/pieces/colors and
// used to populate the correction color picker. Cached per backend base so the
// palette is fetched once per machine per session rather than on every open.

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
		cache.set(base, results);
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

// The LEGO color a piece's color id or name refers to (Brickognize and the
// machine report either), or null when it is not one of LEGO_COLORS.
export function findLegoColor(
	color_id: string | null | undefined,
	color_name: string | null | undefined
): LegoColor | null {
	if (color_id) {
		const by_id = LEGO_COLORS.find((c) => c.id === color_id);
		if (by_id) return by_id;
	}
	if (color_name) {
		const lower = color_name.toLowerCase();
		const by_name = LEGO_COLORS.find((c) => c.name.toLowerCase() === lower);
		if (by_name) return by_name;
	}
	return null;
}
