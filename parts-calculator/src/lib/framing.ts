// Aluminium framing pieces for the machine — 2020 T-slot extrusion (20×20 mm,
// 6 mm slot), cut from 1 m black-anodized bars.
//
// Pieces split into two kinds, mirroring how the machine is built:
//   • per-layer — quantity scales with the layer count N
//   • const     — one set per machine, independent of N (the interface/base)
//
// Tolerance-sensitive pieces (C, D, E, F) are cut 6 mm short so the frame
// doesn't pinch the chute — 6 mm (vs ¼″) keeps every length a whole number.
// The short interface spoke (H) stays at CAD length, same as the layer spoke (B).

export const STOCK_MM = 1000;
export const CLEARANCE_MM = 6; // trim on tolerance-sensitive pieces (was ¼″; 6 mm keeps lengths whole)

// per-layer scales with the layer count; interface + feet are one set per machine
export type PieceCategory = 'per-layer' | 'interface' | 'feet';

export type FramingPiece = {
	letter: string;
	name: string;
	cadLen: number; // nominal design length from CAD (mm)
	len: number; // actual cut length — cadLen minus any tolerance trim (mm)
	category: PieceCategory;
	from: string; // human note on where the quantity comes from
	badge: string; // marker colour for this piece (from the shop paint key)
	optional?: boolean; // not part of the standard build — starts off, excluded from the family render
	// Why this piece can come out at zero for some layer counts. A piece with
	// this note stays in the table at ×0 instead of vanishing, because a piece
	// that is simply absent reads as a missing part rather than a deliberate one
	// (people have hit this with C at 1 and 2 layers).
	zeroNote?: string;
	qtyFor: (n: number) => number;
};

export function scalesWithLayers(c: PieceCategory): boolean {
	return c === 'per-layer';
}

export const FRAMING_PIECES: FramingPiece[] = [
	// ---- per layer (×N) ----
	{ letter: 'A', name: 'Outer horizontal', cadLen: 320, len: 320, category: 'per-layer', from: '6 per layer', badge: '#e08a97', qtyFor: (n) => 6 * n },
	{ letter: 'B', name: 'Spoke', cadLen: 158, len: 158, category: 'per-layer', from: '6 per layer', badge: '#d63b2f', qtyFor: (n) => 6 * n },
	{
		letter: 'C',
		name: 'Layer vertical support',
		cadLen: 160,
		len: 160 - CLEARANCE_MM,
		category: 'per-layer',
		from: '6 per layer, above the bottom 2',
		badge: '#ffffff',
		zeroNote:
			'The bottom two layers do not use C. One foot extension (D) spans both of them in place of a C on each, so C is only cut from 3 layers up.',
		qtyFor: (n) => 6 * Math.max(0, n - 2)
	},
	// ---- interface (one set per machine) ----
	{ letter: 'E', name: 'Interface spoke (long)', cadLen: 244, len: 244 - CLEARANCE_MM, category: 'interface', from: 'per machine', badge: '#1c1c1c', qtyFor: () => 6 },
	{ letter: 'F', name: 'Interface vertical support', cadLen: 280, len: 280 - CLEARANCE_MM, category: 'interface', from: 'per machine', badge: '#e6c24f', qtyFor: () => 6 },
	{ letter: 'G', name: 'Horizontal interface frame', cadLen: 320, len: 320, category: 'interface', from: 'per machine', badge: '#e08a97', qtyFor: () => 6 },
	{ letter: 'H', name: 'Interface spoke (short)', cadLen: 158, len: 158, category: 'interface', from: 'per machine · same as spoke B', badge: '#d63b2f', qtyFor: () => 6 },
	// optional — 10.5″ (267 mm), 3 per machine when enabled
	{ letter: 'I', name: 'Bulk bucket support', cadLen: 267, len: 267, category: 'interface', from: 'per machine · optional', badge: '#7c8330', optional: true, qtyFor: () => 3 },
	// ---- feet (bottom 2 layers span into one piece, in place of a C each) ----
	{
		letter: 'D',
		name: 'Foot extension',
		cadLen: 1.5 * 160,
		len: 1.5 * (160 - CLEARANCE_MM),
		category: 'feet',
		from: 'replaces C on the bottom 2 layers · 1.5 × C',
		badge: '#1f3a93',
		zeroNote:
			'A foot extension joins the bottom two layers into one piece, so it is only cut from 2 layers up.',
		qtyFor: (n) => (n >= 2 ? 6 : 0)
	}
];

export type LengthGroup = {
	len: number;
	qty: number;
	letters: string[];
	names: string[];
	label: string; // "A/G"
	category: 'per-layer' | 'per-machine' | 'mixed';
};

// Collapse pieces that share a length into one bundle, using the layer count to
// resolve per-layer quantities. Pieces with zero quantity at this N are dropped.
export function lengthGroups(n: number, pieces: FramingPiece[] = FRAMING_PIECES): LengthGroup[] {
	const byLen = new Map<string, LengthGroup>();
	for (const p of pieces) {
		if (p.optional) continue; // optional pieces aren't part of the standard family render
		const qty = p.qtyFor(n);
		if (qty <= 0) continue;
		const key = p.len.toFixed(3);
		const scale = scalesWithLayers(p.category) ? 'per-layer' : 'per-machine';
		let g = byLen.get(key);
		if (!g) {
			g = { len: p.len, qty: 0, letters: [], names: [], label: '', category: scale };
			byLen.set(key, g);
		}
		g.qty += qty;
		g.letters.push(p.letter);
		g.names.push(p.name);
		if (g.category !== scale) g.category = 'mixed';
	}
	const groups = [...byLen.values()];
	for (const g of groups) g.label = g.letters.join('/');
	groups.sort((a, b) => b.len - a.len); // longest first
	return groups;
}
