// What a whole machine costs a builder, in parts, filament and hours, computed
// at build time from the parts catalog so the Overview page never carries a
// number somebody typed in by hand.
//
// Every figure here is derived from parts-calculator's generated catalog using
// that app's own resolvers, ported:
//   - printed parts  -> `quantities` x `effectiveMult` (src/lib/filament.ts)
//   - bins and funnels -> the `variantCount` overrides in the calculator's
//     src/routes/+page.svelte, which are keyed off each layer's third/half size
//     rather than off `quantities`
//   - hardware       -> `resolveHardwareTotals('machine', layers)` walked over
//     `assemblies`, falling back to `sheet_qty` exactly as `hardwareTotalQty` does
// Change the catalog and these numbers move on the next build. Nothing is
// estimated: filament weights and print times are the slicer's own output.
import catalog from '../../../../parts-calculator/src/lib/data/catalog.generated.json';

const gen = catalog as any;

/** Bins are optional and are counted separately everywhere on the page: a
 *  builder can drop in boxes they already own instead of printing 90 of these. */
const BIN_IDS = new Set([
	'bin-half-left',
	'bin-half-right',
	'bin-third-left',
	'bin-third-center',
	'bin-third-rightback'
]);

/** Hardware categories that are "electrical" to a reader looking at a bench:
 *  anything that takes a wire, a board or a lens. The rest is fasteners,
 *  bearings and feet. */
const ELECTRICAL = new Set([
	'Electronics',
	'Custom PCBs',
	'Computer',
	'Cameras',
	'Motors',
	'Power supply',
	'Wire harness'
]);

const SCREWS = 'Screws';
const EXTRUSION = 'Aluminum extrusion (2020)';

type Line = { part?: string; assembly?: string; param?: string; args?: Record<string, string>; qty: number | string };

const sectionScales = new Map<string, boolean>(
	(gen.sections ?? []).map((s: any) => [s.id, !!s.scales_with_layers])
);
const hardwareById = new Map<string, any>((gen.hardware ?? []).map((h: any) => [h.id, h]));
const partById = new Map<string, any>((gen.parts ?? []).map((p: any) => [p.id, p]));
const assemblyById = new Map<string, any>((gen.assemblies ?? []).map((a: any) => [a.id, a]));

/** Port of the calculator's `effectiveMult`. */
function effectiveMult(part: any, sectionId: string, layers: number): number {
	if (sectionId === 'layer') {
		if (part.layer_scope === 'non-bottom') return Math.max(0, layers - 1);
		if (part.layer_scope === 'bottom-only') return layers >= 1 ? 1 : 0;
	}
	return sectionScales.get(sectionId) ? layers : 1;
}

/** Port of the calculator's `variantCount`, for an all-third-width tower: every
 *  layer takes one third funnel and 18 bins (3 designs x 6 sections). Third is
 *  the denser of the two layer sizes and the one the page quotes. */
function variantCount(id: string, layers: number): number | null {
	switch (id) {
		case 'funnel-third':
			return layers;
		case 'funnel-half':
			return 0;
		case 'bin-third-left':
		case 'bin-third-center':
		case 'bin-third-rightback':
			return layers * 6;
		case 'bin-half-left':
		case 'bin-half-right':
			return 0;
		default:
			return null;
	}
}

function partQty(part: any, layers: number): number {
	const v = variantCount(part.id, layers);
	if (v !== null) return v;
	let n = 0;
	for (const [section, qty] of Object.entries(part.quantities ?? {}))
		n += (qty as number) * effectiveMult(part, section, layers);
	return n;
}

/** Port of the calculator's `lineQty`. */
function lineQty(line: Line, layers: number): number {
	if (line.qty === 'per-layer') return layers;
	if (line.qty === 'non-bottom-layers') return Math.max(0, layers - 1);
	if (line.qty === 'middle-layers') return Math.max(0, layers - 2);
	return line.qty as number;
}

/** Port of `resolveHardwareTotals` + `hardwareTotalQty`: walk the machine tree,
 *  then fall back to the BOM sheet count for anything the tree does not place. */
function hardwareTotals(layers: number): Map<string, number> {
	const acc = new Map<string, number>();
	const walk = (id: string, mult: number, args?: Record<string, string>) => {
		const asm = assemblyById.get(id);
		for (const raw of (asm?.lines ?? []) as Line[]) {
			const line: Line = { ...raw };
			if (line.param)
				line.part = args?.[line.param] ?? asm?.params?.[line.param]?.default ?? '';
			const q = lineQty(line, layers) * mult;
			if (line.assembly) {
				walk(line.assembly, q, line.args);
			} else if (line.part) {
				if (hardwareById.has(line.part)) {
					acc.set(line.part, (acc.get(line.part) ?? 0) + q);
					continue;
				}
				for (const r of partById.get(line.part)?.requires ?? [])
					acc.set(r.part, (acc.get(r.part) ?? 0) + r.qty * q);
			}
		}
	};
	walk('machine', 1);

	const out = new Map<string, number>();
	for (const h of hardwareById.values()) {
		const fromTree = acc.get(h.id);
		if (fromTree != null) {
			out.set(h.id, fromTree);
		} else if (h.sheet_qty?.per_machine != null) {
			out.set(h.id, h.sheet_qty.per_machine);
		} else if (h.sheet_qty?.per_layer != null) {
			out.set(h.id, h.sheet_qty.per_layer * layers);
		}
	}
	return out;
}

export type ScaleFigures = {
	layers: number;
	bins: number;
	printed: number;
	designs: number;
	printed_kg: string;
	printed_hours: number;
	printed_days: number;
	bins_kg: string;
	bins_hours: number;
	screws: number;
	screw_sizes: number;
	heat_inserts: number;
	tnuts: number;
	electrical: number;
	other: number;
	extrusion: number;
	extrusion_lengths: number;
	extrusion_m: string;
	lasercut: number;
	total: number;
};

export function scaleFor(layers: number): ScaleFigures {
	let printed = 0;
	let designs = 0;
	let bins = 0;
	let grams = 0;
	let seconds = 0;
	let binGrams = 0;
	let binSeconds = 0;

	for (const p of gen.parts ?? []) {
		if (!Object.keys(p.quantities ?? {}).length) continue;
		const q = partQty(p, layers);
		if (q <= 0) continue;
		if (BIN_IDS.has(p.id)) {
			bins += q;
			binGrams += (p.grams ?? 0) * q;
			binSeconds += (p.print_seconds ?? 0) * q;
		} else {
			printed += q;
			designs += 1;
			grams += (p.grams ?? 0) * q;
			seconds += (p.print_seconds ?? 0) * q;
		}
	}

	const totals = hardwareTotals(layers);
	const byCategory = new Map<string, number>();
	let screwSizes = 0;
	let extrusionLengths = 0;
	let heatInserts = 0;
	let tnuts = 0;
	let extrusionMm = 0;
	for (const [id, qty] of totals) {
		if (!qty) continue;
		const h = hardwareById.get(id);
		byCategory.set(h.category, (byCategory.get(h.category) ?? 0) + qty);
		if (h.category === SCREWS) screwSizes += 1;
		if (h.category === EXTRUSION) {
			extrusionLengths += 1;
			extrusionMm += (h.cots?.length_mm ?? 0) * qty;
		}
		if (h.category === 'Heat inserts') heatInserts += qty;
		if (h.cots?.type === 't-nut') tnuts += qty;
	}

	const screws = byCategory.get(SCREWS) ?? 0;
	const extrusion = byCategory.get(EXTRUSION) ?? 0;
	let electrical = 0;
	let other = 0;
	for (const [category, qty] of byCategory) {
		if (category === SCREWS || category === EXTRUSION) continue;
		if (ELECTRICAL.has(category)) electrical += qty;
		else other += qty;
	}
	const lasercut = (gen.lasercut ?? []).length;

	return {
		layers,
		bins,
		printed,
		designs,
		printed_kg: (grams / 1000).toFixed(1),
		printed_hours: Math.round(seconds / 3600),
		printed_days: Math.round(seconds / 3600 / 24),
		bins_kg: (binGrams / 1000).toFixed(1),
		bins_hours: Math.round(binSeconds / 3600),
		screws,
		screw_sizes: screwSizes,
		heat_inserts: heatInserts,
		tnuts,
		electrical,
		other,
		extrusion,
		extrusion_lengths: extrusionLengths,
		extrusion_m: (extrusionMm / 1000).toFixed(1).replace(/\.0$/, ''),
		lasercut,
		total: printed + screws + electrical + other + extrusion + lasercut
	};
}

/** What the Overview page renders. `small` and `large` are the two towers the
 *  comparison sets side by side; the slicer settings are quoted so a reader can
 *  tell whether the print figures apply to their own printer. */
export const buildScale = {
	small: scaleFor(3),
	large: scaleFor(5),
	printer: gen.settings?.printer ?? '',
	process: gen.settings?.process ?? '',
	filament: gen.settings?.filament ?? '',
	infill: gen.settings?.infill_density ?? ''
};
