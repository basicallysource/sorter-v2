// CIE Lab conversion + distance, shared by the color-labeling views. Lab is what
// "looks similar" means here — RGB distance would call navy and brown neighbours.

export type Lab = [number, number, number];

export function hexToLab(hex: string | null): Lab | null {
	if (!hex) return null;
	const m = hex.replace('#', '');
	if (m.length < 6) return null;
	const r = parseInt(m.slice(0, 2), 16);
	const g = parseInt(m.slice(2, 4), 16);
	const b = parseInt(m.slice(4, 6), 16);
	if ([r, g, b].some(Number.isNaN)) return null;
	const lin = (c: number) => {
		c /= 255;
		return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
	};
	const R = lin(r);
	const G = lin(g);
	const B = lin(b);
	const X = (R * 0.4124 + G * 0.3576 + B * 0.1805) / 0.95047;
	const Y = R * 0.2126 + G * 0.7152 + B * 0.0722;
	const Z = (R * 0.0193 + G * 0.1192 + B * 0.9505) / 1.08883;
	const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
	const fx = f(X);
	const fy = f(Y);
	const fz = f(Z);
	return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
}

export function labDistance(a: Lab, b: Lab): number {
	return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

// Non-basic finishes. A piece is far likelier a plain solid color than a
// pearl/metallic/trans one, so these get down-weighted or hidden when the color
// under consideration is itself solid.
export const EXOTIC_FINISH =
	/pearl|metallic|chrome|satin|trans|glow|speckle|glitter|glitr|milky|opal|iridescent|holo|copper|bionicle|\bgold\b|\bsilver\b/i;

export function isExoticFinish(name: string, isTrans: boolean): boolean {
	return isTrans || EXOTIC_FINISH.test(name);
}

// Modulex (a separate 1960s product line) and the "[Unknown]" placeholder are in
// the palette but no real sorted piece is ever one, so they're pure noise in a
// shortlist — and pricing them wastes room in the BrickLink batch.
const NON_CATALOG = /^(mx |\(not applicable\)|\[unknown\])/i;

export function isNonCatalogColor(name: string): boolean {
	return NON_CATALOG.test(name.trim());
}

export function hexDistance(a: string | null, b: string | null): number | null {
	const la = hexToLab(a);
	const lb = hexToLab(b);
	return la && lb ? labDistance(la, lb) : null;
}

// Lab distance that still reads as "could be confused with this". Wide enough to
// hold reddish brown / brown / dark orange together, tight enough to drop blue.
export const SIMILAR_LAB_DISTANCE = 48;

// The colors a piece could plausibly be, given a guess. Shared so the view that
// asks BrickLink to price a shortlist and the view that renders it can't drift.
export function similarColors<T extends { id: number; name: string; rgb: string | null; is_trans: boolean }>(
	palette: T[],
	guess: T | null,
	maxDistance = SIMILAR_LAB_DISTANCE
): T[] {
	const target = hexToLab(guess?.rgb ?? null);
	if (!guess || !target) return [];
	// A solid guess shouldn't be compared against trans/pearl lookalikes.
	const guessExotic = isExoticFinish(guess.name, guess.is_trans);
	return palette.filter((c) => {
		if (c.id === guess.id) return false;
		if (isNonCatalogColor(c.name)) return false;
		if (!guessExotic && isExoticFinish(c.name, c.is_trans)) return false;
		const lab = hexToLab(c.rgb);
		return lab != null && labDistance(lab, target) <= maxDistance;
	});
}
