/**
 * The print manifest: what to print, how many of each, and which file is which.
 *
 * It is written as plain aligned text rather than CSV on purpose, because its
 * main home is inside the STL zip, where the reader is a person who has just
 * unzipped forty files named `<part>-<uid>-<hash8>.stl` and wants to know what
 * they are and how many to run. It doubles as the record of a build: the uid
 * on each line is the exact design revision, so a manifest kept next to a
 * finished machine still says what went into it.
 */
import { SETTINGS, type Part } from './filament';
import type { ExportSpec } from './csv';

export type ManifestRow = {
	part: Part;
	qty: number;
	/** Machine-required count, when it differs from `qty` (an edited quantity). */
	defaultQty: number;
	gramsEach: number;
	colorName: string;
	/** Basename of the STL as it appears in the zip. */
	file: string;
	/** Assemblies this part goes into, for the "used in" note. */
	usedIn: string[];
};

const pad = (s: string, n: number) => (s.length >= n ? s : s + ' '.repeat(n - s.length));
const padL = (s: string, n: number) => (s.length >= n ? s : ' '.repeat(n - s.length) + s);

/** Aligned, human-first. Returns the whole file body. */
export function printManifest(rows: ManifestRow[], spec: ExportSpec, layerSizes: string[]): string {
	const live = rows.filter((r) => r.qty > 0).sort((a, b) => a.part.name.localeCompare(b.part.name));

	const nameW = Math.max(4, ...live.map((r) => r.part.name.length));
	const colorW = Math.max(5, ...live.map((r) => r.colorName.length));

	const head = [
		'Sorter V2 — print manifest',
		`Generated ${spec.date} · release ${spec.release} · ${spec.layers} layer${spec.layers === 1 ? '' : 's'} (${layerSizes.join(', ')})`,
		`${SETTINGS.printer} · ${SETTINGS.process} · ${SETTINGS.infill_density} ${SETTINGS.infill_pattern.replace('adaptivecubic', 'adaptive cubic')} · ${SETTINGS.filament}`,
		''
	];

	const columns =
		`${padL('QTY', 4)}  ${pad('PART', nameW)}  ${pad('UID', 4)}  ${padL('EACH', 7)}  ${padL('TOTAL', 8)}  ${pad('COLOR', colorW)}  FILE`;

	const body = live.map((r) => {
		const total = r.gramsEach * r.qty;
		return (
			`${padL(String(r.qty), 4)}  ${pad(r.part.name, nameW)}  ${pad(r.part.uid, 4)}  ` +
			`${padL(`${r.gramsEach.toFixed(0)} g`, 7)}  ${padL(`${total.toFixed(0)} g`, 8)}  ` +
			`${pad(r.colorName, colorW)}  ${r.file}`
		);
	});

	const pieces = live.reduce((n, r) => n + r.qty, 0);
	const grams = live.reduce((n, r) => n + r.gramsEach * r.qty, 0);
	const foot = [
		'',
		`${live.length} part${live.length === 1 ? '' : 's'} · ${pieces} piece${pieces === 1 ? '' : 's'} · ${(grams / 1000).toFixed(2)} kg of filament`
	];

	// Only worth saying when it happened: a quantity that is not the machine's.
	const edited = live.filter((r) => r.qty !== r.defaultQty);
	if (edited.length) {
		foot.push(
			'',
			'Edited quantities (the machine calls for a different number):',
			...edited.map((r) => `  ${r.part.name}: printing ${r.qty}, machine needs ${r.defaultQty}`)
		);
	}

	// A shared part is the one thing a flat list cannot show, so say it here.
	const shared = live.filter((r) => r.usedIn.length > 1);
	if (shared.length) {
		foot.push(
			'',
			'Used in more than one place:',
			...shared.map((r) => `  ${r.part.name}: ${r.usedIn.join(', ')}`)
		);
	}

	const missing = rows.filter((r) => r.qty <= 0);
	if (missing.length) {
		foot.push('', `Not printing (${missing.length}): ${missing.map((r) => r.part.name).join(', ')}`);
	}

	return [...head, columns, '─'.repeat(columns.length), ...body, ...foot, ''].join('\n');
}

/** Filename for the standalone download; the copy inside the zip is always
 *  `print-manifest.txt` so it sorts to the top and is obvious. */
export function manifestFilename(spec: ExportSpec): string {
	return `sorter-${spec.release}-print-manifest-${spec.layers}-layer-${spec.date}.txt`;
}
