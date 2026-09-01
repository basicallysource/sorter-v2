/**
 * CSV export of the hardware list.
 *
 * The point is that the file stands on its own: someone should be able to hand
 * it to an assistant and ask "which screw multipacks cover 90% of this?" and
 * have every fact needed to answer — thread, length, head type, counts, pack
 * sizes, prices, and where each item is used.
 */
import { csvText, preamble, type ExportSpec } from '$lib/csv';
import { usagePaths, type Hardware, type Vendor } from '$lib/filament';

const COLUMNS = [
	'id',
	'name',
	'category',
	'type',
	'thread',
	'length_mm',
	'head',
	'qty_needed',
	'qty_source',
	'buy_units',
	'unit',
	'vendor',
	'region',
	'unit_price_usd',
	'pack_qty',
	'packs_to_buy',
	'est_cost_usd',
	'price_as_of',
	'url',
	'description',
	'note',
	'specs',
	'used_in'
] as const;

/** Where an item lives, as a readable path — "machine > feeder > c-channel",
 *  with the printed part named when the hardware is committed to one. */
function usedIn(h: Hardware, layers: number): string {
	return usagePaths(h.id, layers)
		.map((p) => {
			const chain = p.steps.map((s) => s.assembly.name).join(' > ');
			return `${chain}${p.via ? ` > ${p.via.name}` : ''} (${p.qty})`;
		})
		.join(' | ');
}

export function hardwareCsv(
	items: Hardware[],
	spec: ExportSpec,
	opts: {
		qty: (h: Hardware) => number | null;
		qtySource: (h: Hardware) => string | null;
		buyUnits: (h: Hardware, qty: number | null) => number | null;
		vendor: (h: Hardware) => Vendor | null;
		packs: (v: Vendor, qty: number) => number;
	}
): string {
	const rows = items.map((h) => {
		const qty = opts.qty(h);
		const units = opts.buyUnits(h, qty);
		const v = opts.vendor(h) ?? h.sourcing?.vendors?.[0] ?? null;
		// packs only mean something when the listing actually sells in packs;
		// otherwise the buyer counts individual pieces and "1 pack" would be a lie
		const packs = v?.pack_qty && units != null ? opts.packs(v, units) : null;
		const cost = v?.price != null && packs != null ? +(packs * v.price).toFixed(2) : null;
		return [
			h.id,
			h.name,
			h.category,
			h.cots?.type,
			h.cots?.size,
			h.cots?.length_mm,
			h.cots?.variant,
			qty,
			opts.qtySource(h),
			units,
			h.stock ? h.stock.unit_label : 'each',
			v?.vendor ?? v?.region,
			v?.region,
			v?.currency && v.currency !== 'USD' ? '' : v?.price,
			v?.pack_qty,
			packs,
			cost,
			v?.as_of,
			v?.url,
			h.description,
			h.note,
			(h.attributes ?? []).map((a) => `${a.label}: ${a.value}`).join('; '),
			usedIn(h, spec.layers)
		];
	});
	return (
		preamble(spec, 'hardware list', [
			`# Items: ${items.length}. Quantities marked qty_source=tree are summed from the`,
			'# machine assembly tree; sheet means a hand count not yet placed in it.'
		]) + csvText(COLUMNS, rows)
	);
}
