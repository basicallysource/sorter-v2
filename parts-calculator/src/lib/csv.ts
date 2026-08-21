/**
 * Shared CSV plumbing for the export buttons.
 *
 * Every export follows the same shape: a commented preamble naming the machine
 * and configuration, then a table. The point is that the file stands on its own
 * — hand it to someone (or something) with no access to the site and every fact
 * needed to act on it is in there.
 */

/** The machine an export was resolved for. Only the release is fixed today;
 *  the layer count is the part that actually varies per build. */
export type ExportSpec = { release: string; layers: number; date: string };

export const RELEASE = '2.0';

/** Where the site lives. Exports get absolute URLs against this rather than
 *  whatever host produced them, so a file made on localhost still resolves. */
export const SITE_URL = 'https://parts-calculator.basically.website';

/** The builder's own date, not UTC — this lands in a filename they'll read. */
export function today(): string {
	const d = new Date();
	const pad = (n: number) => String(n).padStart(2, '0');
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function exportSpec(layers: number): ExportSpec {
	return { release: RELEASE, layers, date: today() };
}

/** RFC 4180: quote anything containing a comma, quote or newline; double inner quotes. */
export function cell(v: unknown): string {
	if (v == null) return '';
	const s = String(v);
	return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function csvText(columns: readonly string[], rows: unknown[][]): string {
	return [columns.join(','), ...rows.map((r) => r.map(cell).join(','))].join('\n') + '\n';
}

/** Header lines every export shares, plus whatever the page wants to add. */
export function preamble(spec: ExportSpec, title: string, extra: string[] = []): string {
	return (
		[
			`# Sorter ${spec.release} — ${title}`,
			`# Configuration: ${spec.layers} distribution layers`,
			`# Generated: ${spec.date} from ${SITE_URL}`,
			...extra
		].join('\n') + '\n'
	);
}

/** `sorter-2.0-hardware-3-layer-2026-07-18.csv` — release, subject, config, date. */
export function filename(spec: ExportSpec, subject: string): string {
	return `sorter-${spec.release}-${subject}-${spec.layers}-layer-${spec.date}.csv`;
}

/** Hand the file to the browser. Revokes the object URL straight after; the
 *  download is already queued by then. */
export function download(name: string, body: string): void {
	const url = URL.createObjectURL(new Blob([body], { type: 'text/csv;charset=utf-8' }));
	const a = document.createElement('a');
	a.href = url;
	a.download = name;
	a.click();
	URL.revokeObjectURL(url);
}
