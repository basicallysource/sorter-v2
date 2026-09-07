// Aluminium framing pieces for the machine — 2020 T-slot extrusion (20×20 mm,
// 6 mm slot), cut from 1 m black-anodized bars.
//
// THE DATA IS NOT IN THIS FILE. Every 2020 piece is a `kind: cots` part in
// catalog/parts.json with `cots.type === 'extrusion-2020'`, placed in the
// machine tree like anything else, so its cut length, its CAD length, its
// marker letters and its quantity are the same numbers the Hardware tab and
// the docs site read. This module is the typed view over those records, the
// way lasercut.ts is for the sheet parts.
//
// What IS authored here is presentation: the marker colour, which group a
// piece belongs to, and the sentence saying where its quantity comes from. A
// part with no entry in STYLE still appears in the cut list on default
// styling — the catalog decides what exists, this file only decides how it
// looks, so a new extrusion piece can never go missing from the cut plan
// again (it did: piece J, sorter-v2#574).
//
// Tolerance-sensitive pieces are cut 6 mm short so the frame doesn't pinch the
// chute — 6 mm (vs ¼″) keeps every length a whole number. That is recorded per
// part as `cots.cad_length_mm` above the cut length, not decided here.

import raw from '$lib/data/catalog.generated.json';
import { resolveHardwareTotals } from '$lib/filament';

export const STOCK_MM = 1000;
export const CLEARANCE_MM = 6; // trim on tolerance-sensitive pieces (was ¼″; 6 mm keeps lengths whole)

// The frame is the hex rings and what stands between them; the feeder group is
// 2020 that holds a C-channel up rather than the machine.
export type PieceGroup = 'frame' | 'feeder';

type Style = {
	group: PieceGroup;
	badge: string; // marker colour for this piece (from the shop paint key)
	from: string; // where the quantity comes from, in tree terms
	// Why this piece can come out at zero for some layer counts. A piece with
	// this note stays in the table at ×0 instead of vanishing, because a piece
	// that is simply absent reads as a missing part rather than a deliberate one
	// (people have hit this with C at one layer).
	zeroNote?: string;
};

const STYLE: Record<string, Style> = {
	'ext-2020-ag': {
		group: 'frame',
		badge: '#e08a97',
		from: '6 on every hex frame ring · one ring per layer, plus the interface frame'
	},
	'ext-2020-bh': {
		group: 'frame',
		badge: '#d63b2f',
		from: '6 on every hex frame ring · one ring per layer, plus the interface frame'
	},
	'ext-2020-c': {
		group: 'frame',
		badge: '#ffffff',
		from: '6 on every layer above the bottom one',
		zeroNote:
			'A single-layer machine gets no C: the bottom layer stands on foot extensions (D) instead, and the run from it up to the interface frame is not in the model yet. Worth checking against your own build.'
	},
	'ext-2020-d': {
		group: 'frame',
		badge: '#1f3a93',
		from: "6 on the bottom layer, in place of that layer's C · 1.5 × C, so it carries on down to the caster"
	},
	'ext-2020-e': { group: 'frame', badge: '#1c1c1c', from: '1 on each of the 6 interface bracket mounts' },
	'ext-2020-f': { group: 'frame', badge: '#e6c24f', from: '1 on each of the 6 interface bracket mounts' },
	'ext-2020-c1': {
		group: 'feeder',
		badge: '#2a9d8f',
		from: "3 in C-channel 1's support structure · the only 2020 outside the frame"
	}
};

const DEFAULT_STYLE: Style = {
	group: 'frame',
	badge: '#9a9a94',
	from: 'from the machine tree'
};

export type FramingPiece = {
	id: string; // catalog part id — the key for everything derived
	letters: string[]; // 'A' and 'G' are one part cut to one length, at two rings
	letter: string; // the letters joined, e.g. 'A/G' — what goes on the bar
	name: string;
	cadLen: number; // nominal design length from CAD (mm)
	len: number; // actual cut length — cadLen minus any tolerance trim (mm)
	group: PieceGroup;
	from: string;
	badge: string;
	zeroNote?: string;
	scalesWithLayers: boolean; // derived: does its tree quantity move with the layer count
};

type ExtrusionRecord = {
	id: string;
	name: string;
	cots?: { type?: string; length_mm?: number; cad_length_mm?: number; letters?: string[] } | null;
};

/** Machine totals for every framing piece at this layer count, straight off the
 *  assembly tree — the same resolver the Hardware tab counts screws with. */
export function framingQuantities(layers: number): Map<string, number> {
	return resolveHardwareTotals('machine', layers);
}

const GROUP_ORDER: PieceGroup[] = ['frame', 'feeder'];

// Strip the trailing letter tag the catalog names carry ("Layer vertical
// support (C)"), since the table shows the letters in their own badge column.
function displayName(name: string): string {
	return name.replace(/\s*\([A-Z](?:\/[A-Z])*\)\s*$/, '');
}

export const FRAMING_PIECES: FramingPiece[] = (() => {
	const records = (((raw as Record<string, unknown>).hardware ?? []) as ExtrusionRecord[]).filter(
		(h) => h.cots?.type === 'extrusion-2020'
	);
	// One resolve at each of two layer counts tells us which pieces scale, with
	// no second model of the machine to keep in step.
	const at3 = framingQuantities(3);
	const at4 = framingQuantities(4);
	return records
		.map((h) => {
			const style = STYLE[h.id] ?? DEFAULT_STYLE;
			const len = h.cots?.length_mm ?? 0;
			const letters = h.cots?.letters?.length ? h.cots.letters : ['?'];
			return {
				id: h.id,
				letters,
				letter: letters.join('/'),
				name: displayName(h.name),
				cadLen: h.cots?.cad_length_mm ?? len,
				len,
				group: style.group,
				from: style.from,
				badge: style.badge,
				zeroNote: style.zeroNote,
				scalesWithLayers: (at3.get(h.id) ?? 0) !== (at4.get(h.id) ?? 0)
			};
		})
		.sort(
			(a, b) =>
				GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group) || b.len - a.len
		);
})();

export type LengthGroup = {
	len: number;
	qty: number;
	letters: string[];
	names: string[];
	label: string; // "A/G"
	category: 'per-layer' | 'per-machine' | 'mixed';
};

// Collapse pieces that share a length into one bundle, using the layer count to
// resolve quantities off the tree. Pieces with zero quantity at this N are
// dropped.
export function lengthGroups(n: number, pieces: FramingPiece[] = FRAMING_PIECES): LengthGroup[] {
	const totals = framingQuantities(n);
	const byLen = new Map<string, LengthGroup>();
	for (const p of pieces) {
		const qty = totals.get(p.id) ?? 0;
		if (qty <= 0) continue;
		const key = p.len.toFixed(3);
		const scale = p.scalesWithLayers ? 'per-layer' : 'per-machine';
		let g = byLen.get(key);
		if (!g) {
			g = { len: p.len, qty: 0, letters: [], names: [], label: '', category: scale };
			byLen.set(key, g);
		}
		g.qty += qty;
		g.letters.push(...p.letters);
		g.names.push(p.name);
		if (g.category !== scale) g.category = 'mixed';
	}
	const groups = [...byLen.values()];
	for (const g of groups) g.label = g.letters.join('/');
	groups.sort((a, b) => b.len - a.len); // longest first
	return groups;
}
