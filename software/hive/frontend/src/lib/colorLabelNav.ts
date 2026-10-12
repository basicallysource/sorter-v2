// The Piece samples list: its filters in the URL, and the queue the grid and
// the labeling pane step through (lib/reviewQueue).

import { api, type BrickLinkColor, type ColorLabelPieceCard, type ColorLabelSort, type Machine } from '$lib/api';
import { queueFor, readMachines, writeMachines, type ReviewQueue } from '$lib/reviewQueue.svelte';

export type PieceKey = { machine_id: string; piece_uuid: string };

export function pieceKey(k: PieceKey): string {
	return `${k.machine_id}|${k.piece_uuid}`;
}

// The palette is effectively static; cache it so navigating piece-to-piece
// doesn't refetch ~200 colors each time.
let colorsCache: BrickLinkColor[] | null = null;

export async function getColors(): Promise<BrickLinkColor[]> {
	if (colorsCache == null) {
		const res = await api.colorLabelColors();
		// Drop non-answers: id<=0 is "(Not Applicable)"; "Mx …" is Modulex.
		colorsCache = res.results.filter((c) => c.id > 0 && !c.name.startsWith('Mx '));
	}
	return colorsCache;
}

// The machine list for the filter sidebar is fleet metadata that changes
// rarely — cache it for the session instead of refetching on every visit.
let machinesCache: Machine[] | null = null;

export async function getMachinesCached(): Promise<Machine[]> {
	if (machinesCache == null) {
		machinesCache = await api.getMachines({ scope: 'all' });
	}
	return machinesCache;
}

export type PieceFilters = { sort: ColorLabelSort; machineIds: string[]; withCandidates: boolean };

const SORT_VALUES: ColorLabelSort[] = [
	'priority',
	'recent',
	'oldest',
	'least_color',
	'most_color',
	'least_crop',
	'most_crop',
	'rare_color',
	'needs_me'
];

// Filters ↔ URL query params, so a shared or reloaded link shows the same list.
// Defaults (priority, every machine, has-candidates) are left out of the URL.
export function filtersToSearch(f: PieceFilters, sp = new URLSearchParams()): URLSearchParams {
	sp.delete('sort');
	sp.delete('candidates');
	if (f.sort !== 'priority') sp.set('sort', f.sort);
	writeMachines(sp, f.machineIds);
	if (!f.withCandidates) sp.set('candidates', '0');
	return sp;
}

export function filtersFromSearch(sp: URLSearchParams): PieceFilters {
	const rawSort = sp.get('sort');
	return {
		sort: SORT_VALUES.includes(rawSort as ColorLabelSort) ? (rawSort as ColorLabelSort) : 'priority',
		machineIds: readMachines(sp),
		withCandidates: sp.get('candidates') !== '0'
	};
}

export function filtersKey(f: PieceFilters): string {
	return `${f.sort}|${[...f.machineIds].sort().join(',')}|${f.withCandidates ? 1 : 0}`;
}

// The queue for these filters, shared by the grid and the pane for the session.
export function pieceQueue(f: PieceFilters): ReviewQueue<ColorLabelPieceCard> {
	return queueFor<ColorLabelPieceCard>('pieces', filtersKey(f), {
		key: pieceKey,
		fetch: (cursor) =>
			api.colorLabelPieces({
				sort: f.sort,
				machineIds: f.machineIds,
				withCandidates: f.withCandidates,
				limit: 60,
				cursor
			})
	});
}
