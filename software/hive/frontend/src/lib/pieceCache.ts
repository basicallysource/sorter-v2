// What the labeling pane shows for a piece, fetched ahead of time: the pieces
// after the open one, and a card the pointer rests on. Opening a piece then
// shows what is here at once (the pane refreshes it in the background), and its
// pictures are already in the browser's cache.

import { api, type ColorLabelPieceDetail, type PossibleCropsResult } from '$lib/api';

type Entry = {
	detail: Promise<ColorLabelPieceDetail>;
	crops: Promise<PossibleCropsResult>;
	at: number;
};

// Kept this long before a prefetch asks again.
const FRESH_MS = 2 * 60 * 1000;
const MAX_ENTRIES = 40;
// Candidate crops preloaded per piece (the pane shows them first).
const PRELOAD_CANDIDATES = 24;

const entries = new Map<string, Entry>();
const preloaded = new Set<string>();

function keyOf(machineId: string, pieceUuid: string): string {
	return `${machineId}|${pieceUuid}`;
}

function preload(url: string): void {
	if (preloaded.has(url)) return;
	preloaded.add(url);
	if (preloaded.size > 2000) preloaded.delete(preloaded.values().next().value as string);
	const img = new Image();
	img.decoding = 'async';
	img.src = url;
}

function remember(k: string, entry: Entry): void {
	entries.delete(k);
	entries.set(k, entry);
	while (entries.size > MAX_ENTRIES) entries.delete(entries.keys().next().value as string);
	// A load that failed is not kept, so the pane asks again.
	const drop = () => {
		if (entries.get(k) === entry) entries.delete(k);
	};
	entry.detail.catch(drop);
	entry.crops.catch(drop);
}

/** Fetch a piece's pane data, and its pictures, unless that happened lately. */
export function prefetchPiece(machineId: string, pieceUuid: string): void {
	const k = keyOf(machineId, pieceUuid);
	const have = entries.get(k);
	if (have && Date.now() - have.at < FRESH_MS) return;
	const entry: Entry = {
		detail: api.colorLabelPieceDetail(machineId, pieceUuid),
		crops: api.possibleCrops(machineId, pieceUuid),
		at: Date.now()
	};
	remember(k, entry);
	entry.detail
		.then((d) => {
			for (const im of d.images) preload(im.url ?? api.colorLabelImageUrl(machineId, pieceUuid, im.seq));
		})
		.catch(() => {});
	entry.crops
		.then((c) => {
			for (const cand of c.candidates.slice(0, PRELOAD_CANDIDATES)) {
				if (cand.available) preload(cand.thumb_url ?? api.channelCropLabelImageUrl(machineId, cand.local_id));
			}
		})
		.catch(() => {});
}

/** The pane data fetched for a piece, if any (in flight or done); it is
 * handed over once, so a later open fetches afresh. */
export function takePiece(
	machineId: string,
	pieceUuid: string
): { detail: Promise<ColorLabelPieceDetail>; crops: Promise<PossibleCropsResult> } | null {
	const k = keyOf(machineId, pieceUuid);
	const entry = entries.get(k);
	if (!entry) return null;
	entries.delete(k);
	return entry;
}

/** Fetch these pieces ahead (the next ones in a list). */
export function prefetchPieces(keys: { machine_id: string; piece_uuid: string }[]): void {
	for (const k of keys) prefetchPiece(k.machine_id, k.piece_uuid);
}
