// Working list for stepping through pieces on the single-piece labeling route.
// Seeded from whatever order the dashboard grid is showing (so you label in that
// order), and lazily extended from the same sorted endpoint when you reach the
// end. A module singleton so the order survives client-side navigation between
// /piece-bboxes and /piece-bboxes/[machine_id]/[piece_uuid].

import { api, type BrickLinkColor, type ColorLabelSort } from '$lib/api';

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

let queue: PieceKey[] = [];
let sort: ColorLabelSort = 'needs_me';
let nextOffset = 0;
let hasMore = true;
let loading = false;

function sameKey(a: PieceKey, b: PieceKey): boolean {
	return a.machine_id === b.machine_id && a.piece_uuid === b.piece_uuid;
}

function indexOf(k: PieceKey): number {
	return queue.findIndex((q) => sameKey(q, k));
}

export function seed(items: PieceKey[], sortUsed: ColorLabelSort, offsetAfter: number, more: boolean): void {
	queue = items.map((k) => ({ machine_id: k.machine_id, piece_uuid: k.piece_uuid }));
	sort = sortUsed;
	nextOffset = offsetAfter;
	hasMore = more;
}

async function fetchMore(): Promise<boolean> {
	if (loading || !hasMore) return false;
	loading = true;
	try {
		const page = await api.colorLabelPieces({ sort, limit: 60, offset: nextOffset });
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
