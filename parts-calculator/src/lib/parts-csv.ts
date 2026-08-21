/**
 * CSV exports for the printed parts, the machine assembly tree, and the
 * aluminium cut plan. Each carries the download URL for anything downloadable,
 * so the file is enough to actually print or cut from — the STL links are
 * content-addressed and permanent, so they don't rot.
 */
import { csvText, preamble, SITE_URL, type ExportSpec } from '$lib/csv';
import {
	getAssembly,
	getHardware,
	getLasercut,
	getPart,
	lineQty,
	plainDescription,
	SECTIONS,
	sectionQty,
	effectiveMult,
	plannedChangesFor,
	type Part
} from '$lib/filament';
import type { Bin } from '$lib/cutplan';

/** Site-relative asset paths are useless in a file that travels; make them whole.
 *  Against the published site, not the host that generated the file. */
function absolute(url: string): string {
	return url.startsWith('/') ? SITE_URL + url : url;
}

// ------------------------------------------------------------ printed parts

const PART_COLUMNS = [
	'id',
	'name',
	'sections',
	'qty_per_machine',
	'grams_each',
	'grams_total',
	'support_grams_each',
	'support_intentional',
	'print_minutes_each',
	'color',
	'version',
	'updated',
	'optional',
	'low_tolerance',
	'notes',
	'stl_url',
	'render_url',
	'onshape'
] as const;

/** A part is one row PER COLOR, not one row per part: the stator is printed 3×
 *  charcoal and 1× ash gray, and a single collapsed row would silently drop the
 *  gray one. Single-color parts — nearly all of them — are still one row. `id`
 *  is therefore not unique; the color column is what separates the rows, and
 *  summing qty/grams over the file still gives the right machine totals. */
export function partsCsv(
	parts: Part[],
	spec: ExportSpec,
	opts: {
		grams: (p: Part) => number; // per unit, honouring the support toggle
		colors: (p: Part) => { name: string; qty: number; sections: string[] }[];
		onshape: (p: Part) => string | null;
	}
): string {
	const sectionName = (id: string) => SECTIONS.find((s) => s.id === id)?.name ?? id;
	const rows = parts.flatMap((p) => {
		const each = opts.grams(p);
		const notes = [
			p.low_tolerance ? `Low tolerance: ${p.low_tolerance_note ?? 'test print recommended'}` : '',
			...plannedChangesFor('parts', p.id).map((change) =>
				`Subject to change ${change.priority}: ${change.name}`
			)
		]
			.filter(Boolean)
			.join(' | ');
		return opts.colors(p).map((c) => [
			p.id,
			p.name,
			c.sections.map(sectionName).join('; '),
			c.qty,
			+each.toFixed(1),
			+(each * c.qty).toFixed(1),
			+p.support_grams.toFixed(1),
			p.support_intentional ? 'yes' : 'no',
			Math.round(p.print_seconds / 60),
			c.name,
			p.version,
			p.updated_at,
			p.optional ? 'yes' : 'no',
			p.low_tolerance ? 'yes' : 'no',
			notes || p.description,
			p.stl,
			absolute(p.render),
			opts.onshape(p)
		]);
	});
	const totalG = rows.reduce((s, r) => s + (r[5] as number), 0);
	const split = rows.length - parts.length;
	return (
		preamble(spec, 'printed parts', [
			`# Parts: ${parts.length}. Total filament: ${(totalG / 1000).toFixed(2)} kg.`,
			`# Rows: ${rows.length}` +
				(split > 0
					? ` — ${split} extra because a part printed in more than one color gets a row per color.`
					: '.'),
			'# grams come from real slicer output, never estimated from volume.',
			'# stl_url is content-addressed and permanent.'
		]) + csvText(PART_COLUMNS, rows)
	);
}

// ----------------------------------------------------------- assembly tree

const TREE_COLUMNS = [
	'depth',
	'path',
	'kind',
	'id',
	'name',
	'qty_each',
	'qty_total',
	'status',
	'joining',
	'grams_each',
	'download_url',
	'description'
] as const;

type TreeRow = unknown[];

/** Walk the tree depth-first, one row per node, quantities multiplied down.
 *  Reads like an indented BOM: the `path` column carries the ancestry so the
 *  file survives being sorted or filtered. */
export function assemblyCsv(root: string, spec: ExportSpec): string {
	const rows: TreeRow[] = [];
	const walk = (id: string, trail: string[], mult: number, depth: number) => {
		const asm = getAssembly(id);
		if (!asm) return;
		const path = [...trail, asm.name];
		rows.push([
			depth,
			path.join(' > '),
			'assembly',
			asm.id,
			asm.name,
			'',
			mult,
			asm.status ?? 'complete',
			(asm.joining ?? []).map((j) => j.method).join('; '),
			'',
			'',
			plainDescription(asm.description)
		]);
		for (const line of asm.lines ?? []) {
			const each = lineQty(line, spec.layers);
			const total = each * mult;
			if (line.assembly) {
				walk(line.assembly, path, total, depth + 1);
				continue;
			}
			if (!line.part) continue;
			const hw = getHardware(line.part);
			const part = getPart(line.part);
			const lc = getLasercut(line.part);
			const name = hw?.name ?? part?.name ?? lc?.name ?? line.part;
			rows.push([
				depth + 1,
				[...path, name].join(' > '),
				hw ? 'hardware' : part ? 'printed' : lc ? 'lasercut' : 'unknown',
				line.part,
				name,
				each,
				total,
				'',
				'',
				part ? +part.grams.toFixed(1) : '',
				part?.stl ?? (lc ? absolute(lc.dxf) : ''),
				hw?.description ?? part?.description ?? lc?.description ?? ''
			]);
			// hardware committed to the printed part itself (inserts, bearings)
			for (const r of part?.requires ?? []) {
				const req = getHardware(r.part);
				rows.push([
					depth + 2,
					[...path, name, req?.name ?? r.part].join(' > '),
					'hardware',
					r.part,
					req?.name ?? r.part,
					r.qty,
					r.qty * total,
					'',
					'',
					'',
					'',
					`Committed to the ${name}`
				]);
			}
		}
	};
	walk(root, [], 1, 0);
	return (
		preamble(spec, 'machine assembly tree', [
			`# Rows: ${rows.length}. qty_each is per parent; qty_total is per machine.`,
			'# Branches marked stub/partial are known to be incomplete.'
		]) + csvText(TREE_COLUMNS, rows)
	);
}

// --------------------------------------------------------- aluminium framing

const FRAMING_COLUMNS = [
	'letter',
	'name',
	'length_mm',
	'qty',
	'scaling',
	'total_mm'
] as const;
const BAR_COLUMNS = ['bar', 'pieces', 'cuts_mm', 'used_mm', 'offcut_mm'] as const;

/** The cut list as the page currently has it — the user's own quantity and
 *  selection overrides included, not the defaults. */
export type FramingRow = { letter: string; name: string; len: number; qty: number; cat: string };

/** Two tables in one file: what to cut, then how to lay it out on the bars. */
export function framingCsv(
	pieces: FramingRow[],
	bins: Bin[],
	spec: ExportSpec,
	stockMm: number,
	kerfMm: number
): string {
	const pieceRows = pieces.map((g) => [
		g.letter,
		g.name,
		+g.len.toFixed(1),
		g.qty,
		g.cat,
		+(g.len * g.qty).toFixed(1)
	]);
	const barRows = bins.map((b, i) => [
		i + 1,
		b.items.map((u) => u.letter).join(' '),
		b.items.map((u) => +u.len.toFixed(1)).join(' + '),
		+b.consumed.toFixed(1),
		+(stockMm - b.consumed).toFixed(1)
	]);
	const totalMm = pieceRows.reduce((s, r) => s + (r[5] as number), 0);
	return (
		preamble(spec, 'aluminium framing', [
			`# 2020 T-slot extrusion. Stock bar ${stockMm} mm, saw kerf ${kerfMm} mm.`,
			`# ${pieceRows.reduce((s, r) => s + (r[3] as number), 0)} pieces, ` +
				`${(totalMm / 1000).toFixed(2)} m of material, ${bins.length} bars to buy.`,
			'# Table 1 is the cut list; table 2 is how they pack onto bars.'
		]) +
		csvText(FRAMING_COLUMNS, pieceRows) +
		'\n' +
		csvText(BAR_COLUMNS, barRows)
	);
}
