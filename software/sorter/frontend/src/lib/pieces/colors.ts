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

// Readable text-on-swatch: white for dark colors, black for light. Mirrors the
// luminance threshold used by lego-colors.ts.
export function swatchTextColor(rgb: string | null | undefined): string {
	const hex = swatchHex(rgb);
	if (!hex) return '#000000';
	const r = parseInt(hex.slice(1, 3), 16) / 255;
	const g = parseInt(hex.slice(3, 5), 16) / 255;
	const b = parseInt(hex.slice(5, 7), 16) / 255;
	const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
	const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
	return luminance > 0.3 ? '#000000' : '#ffffff';
}
