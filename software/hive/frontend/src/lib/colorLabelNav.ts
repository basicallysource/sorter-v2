// Working list for stepping through pieces on the single-piece labeling route.
// Seeded from whatever order the dashboard grid is showing (so you label in that
// order), and lazily extended from the same sorted endpoint when you reach the
// end. A module singleton so the order survives client-side navigation between
// /piece-bboxes and /piece-bboxes/[machine_id]/[piece_uuid].

import {
	api,
	type BrickLinkColor,
	type ColorLabelPieceCard,
	type ColorLabelSort,
	type ColorLabelStats,
	type Machine
} from '$lib/api';

export type PieceKey = { machine_id: string; piece_uuid: string };

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

export type NavFilters = { sort: ColorLabelSort; machineId?: string | null; withCandidates?: boolean };

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

// Filters ↔ URL query params, so the dashboard's filter state survives
// navigation (back from a piece lands on the same filtered list). Defaults
// (priority / all machines / has-candidates) are omitted to keep URLs clean.
export function filtersToSearch(f: NavFilters): string {
	const params = new URLSearchParams();
	if (f.sort !== 'priority') params.set('sort', f.sort);
	if (f.machineId) params.set('machine', f.machineId);
	if (f.withCandidates === false) params.set('candidates', '0');
	return params.toString();
}

export function filtersFromSearch(sp: URLSearchParams): NavFilters {
	const rawSort = sp.get('sort');
	const sort = SORT_VALUES.includes(rawSort as ColorLabelSort) ? (rawSort as ColorLabelSort) : 'priority';
	return {
		sort,
		machineId: sp.get('machine') || null,
		withCandidates: sp.get('candidates') !== '0'
	};
}

export function filtersKey(f: NavFilters): string {
	return `${f.sort}|${f.machineId ?? ''}|${f.withCandidates === false ? 0 : 1}`;
}

// Where "back to the dashboard" should land: the list under the filters the
// working queue was seeded from.
export function dashboardUrl(): string {
	const qs = filtersToSearch(filters);
	return `/piece-bboxes${qs ? `?${qs}` : ''}`;
}

// Snapshot of the dashboard grid (items + stats + scroll) so returning from a
// piece restores the exact list instantly; the page revalidates in the
// background. Module singleton — survives client-side navigation like `queue`.
export type GridSnapshot = {
	key: string;
	items: ColorLabelPieceCard[];
	stats: ColorLabelStats | null;
	offset: number;
	hasMore: boolean;
	scrollY: number;
};

let gridSnapshot: GridSnapshot | null = null;

export function saveGrid(snap: GridSnapshot): void {
	gridSnapshot = snap;
}

export function getGrid(key: string): GridSnapshot | null {
	return gridSnapshot != null && gridSnapshot.key === key ? gridSnapshot : null;
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

let queue: PieceKey[] = [];
let filters: NavFilters = { sort: 'priority', withCandidates: true };
let nextOffset = 0;
let hasMore = true;
let loading = false;

function sameKey(a: PieceKey, b: PieceKey): boolean {
	return a.machine_id === b.machine_id && a.piece_uuid === b.piece_uuid;
}

function indexOf(k: PieceKey): number {
	return queue.findIndex((q) => sameKey(q, k));
}

export function seed(items: PieceKey[], f: NavFilters, offsetAfter: number, more: boolean): void {
	queue = items.map((k) => ({ machine_id: k.machine_id, piece_uuid: k.piece_uuid }));
	filters = f;
	nextOffset = offsetAfter;
	hasMore = more;
}

async function fetchMore(): Promise<boolean> {
	if (loading || !hasMore) return false;
	loading = true;
	try {
		const page = await api.colorLabelPieces({
			sort: filters.sort,
			machineId: filters.machineId,
			withCandidates: filters.withCandidates,
			limit: 60,
			offset: nextOffset
		});
		nextOffset += page.items.length;
		hasMore = page.has_more;
		for (const it of page.items) {
			if (indexOf(it) < 0) queue.push({ machine_id: it.machine_id, piece_uuid: it.piece_uuid });
		}
		return page.items.length > 0;
	} finally {
		loading = false;
	}
}

async function ensureSeeded(): Promise<void> {
	if (queue.length === 0) {
		nextOffset = 0;
		hasMore = true;
		await fetchMore();
	}
}

export async function nextAfter(k: PieceKey): Promise<PieceKey | null> {
	await ensureSeeded();
	let i = indexOf(k);
	if (i < 0) return queue[0] ?? null;
	while (i >= queue.length - 1 && hasMore) await fetchMore();
	return queue[i + 1] ?? null;
}

export async function prevBefore(k: PieceKey): Promise<PieceKey | null> {
	await ensureSeeded();
	const i = indexOf(k);
	return i > 0 ? queue[i - 1] : null;
}

export function position(k: PieceKey): { index: number; total: number; hasMore: boolean } {
	return { index: indexOf(k), total: queue.length, hasMore };
}
