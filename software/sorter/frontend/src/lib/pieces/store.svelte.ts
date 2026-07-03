import type { ClassificationStatus, KnownObjectData } from '$lib/api/events';

export type PieceOrigin = 'rest' | 'ws';

export type BinRef = { x: number; y: number; z: number };

// Mirror of the backend PieceSummary model (server/routers/pieces.py). Every
// data field is optional/nullable — old rows predate several columns.
export type PieceSummary = {
	uuid: string;
	run_id?: string | null;
	seen_at?: number | null;
	recorded_at?: number | null;
	classification_status?: string | null;
	part_id?: string | null;
	part_name?: string | null;
	color_id?: string | null;
	color_name?: string | null;
	category_id?: string | null;
	confidence?: number | null;
	bin?: BinRef | null;
	dead?: boolean;
	has_images?: boolean;
	preview_url?: string | null;
	est_value?: number | null;
};

// GET /api/pieces/{uuid} — tiered envelope. `detail` is the full KnownObject
// payload only when the piece is still in backend memory (detail_available).
export type PieceDetailEnvelope = {
	origin: 'memory' | 'disk';
	summary: PieceSummary;
	detail: KnownObjectData | null;
	detail_available: boolean;
};

export type PiecesListResponse = {
	items: PieceSummary[];
	next_cursor: string | null;
	total: number;
};

// The ONE client piece shape: REST PieceSummary rows and live WS KnownObject
// events both reduce into it. `ws` carries the full live payload for ws-origin
// entries; rest-origin entries are light summaries of already-recorded pieces.
export type Piece = {
	uuid: string;
	origin: PieceOrigin;
	run_id: string | null;
	seen_at: number | null;
	recorded_at: number | null;
	classification_status: string | null;
	part_id: string | null;
	part_name: string | null;
	color_id: string | null;
	color_name: string | null;
	category_id: string | null;
	confidence: number | null;
	bin: BinRef | null;
	dead: boolean;
	has_images: boolean;
	preview_url: string | null;
	est_value: number | null;
	ws: KnownObjectData | null;
};

// Live WS entries carry base64 crops, so cap them like the old ring did; when
// evicted they demote to light rest summaries instead of vanishing.
const WS_ENTRY_LIMIT = 32;
const TOTAL_ENTRY_LIMIT = 400;

// Old backends flagged transport errors as request_failed on an 'unknown'
// status; new ones persist a distinct 'failed'. Fold both into 'failed' so the
// UI has one code path.
export function effectiveStatus(
	status: string | null | undefined,
	request_failed?: boolean | null
): string | null {
	if (status === 'failed') return 'failed';
	if (request_failed && status !== 'classified') return 'failed';
	return status ?? null;
}

function binFromDestination(dest: KnownObjectData['destination_bin']): BinRef | null {
	if (!dest || dest.length !== 3) return null;
	const x = Number(dest[0]);
	const y = Number(dest[1]);
	const z = Number(dest[2]);
	if (!Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(z)) return null;
	return { x, y, z };
}

function pieceFromSummary(s: PieceSummary): Piece {
	return {
		uuid: s.uuid,
		origin: 'rest',
		run_id: s.run_id ?? null,
		seen_at: s.seen_at ?? null,
		recorded_at: s.recorded_at ?? null,
		classification_status: s.classification_status ?? null,
		part_id: s.part_id ?? null,
		part_name: s.part_name ?? null,
		color_id: s.color_id ?? null,
		color_name: s.color_name ?? null,
		category_id: s.category_id ?? null,
		confidence: s.confidence ?? null,
		bin: s.bin ?? null,
		dead: Boolean(s.dead),
		has_images: Boolean(s.has_images),
		preview_url: s.preview_url ?? null,
		est_value: s.est_value ?? null,
		ws: null
	};
}

function pieceFromKnownObject(obj: KnownObjectData): Piece {
	return {
		uuid: obj.uuid,
		origin: 'ws',
		run_id: null,
		seen_at: obj.created_at ?? null,
		recorded_at: obj.distributed_at ?? null,
		classification_status: effectiveStatus(obj.classification_status, obj.request_failed),
		part_id: obj.part_id ?? null,
		part_name: obj.part_name ?? null,
		color_id: obj.color_id ?? null,
		color_name: obj.color_name ?? null,
		category_id: obj.category_id ?? null,
		confidence: obj.confidence ?? null,
		bin: binFromDestination(obj.destination_bin),
		dead: Boolean(obj.dead),
		has_images: Boolean(
			obj.recognition_image_set?.length || obj.latest_captured_crop || obj.thumbnail
		),
		preview_url: obj.brickognize_preview_url ?? null,
		est_value: obj.moving_avg_price ?? null,
		ws: obj
	};
}

export function pieceToSummary(p: Piece): PieceSummary {
	return {
		uuid: p.uuid,
		run_id: p.run_id,
		seen_at: p.seen_at,
		recorded_at: p.recorded_at,
		classification_status: p.classification_status,
		part_id: p.part_id,
		part_name: p.part_name,
		color_id: p.color_id,
		color_name: p.color_name,
		category_id: p.category_id,
		confidence: p.confidence,
		bin: p.bin,
		dead: p.dead,
		has_images: p.has_images,
		preview_url: p.preview_url,
		est_value: p.est_value
	};
}

// Rest-origin rows lack live-only fields (stage, lifecycle timestamps, crops);
// they describe already-completed pieces, so bin/recorded_at stand in for the
// terminal signal.
export function isTerminalPiece(p: Piece): boolean {
	if (p.ws) return p.ws.stage === 'distributed' || p.ws.distributed_at != null;
	return p.bin != null || p.recorded_at != null;
}

// A KnownObjectData-shaped view so components written against the live payload
// can render rest-origin entries without a parallel code path.
export function pieceToKnownObjectView(p: Piece): KnownObjectData {
	if (p.ws) return p.ws;
	const terminal = p.bin != null || p.recorded_at != null;
	return {
		uuid: p.uuid,
		created_at: p.seen_at ?? p.recorded_at ?? 0,
		updated_at: p.recorded_at ?? p.seen_at ?? 0,
		stage: terminal ? 'distributed' : 'created',
		classification_status: (p.classification_status ?? 'unknown') as ClassificationStatus,
		dead: p.dead,
		part_id: p.part_id,
		part_name: p.part_name,
		color_id: p.color_id ?? undefined,
		color_name: p.color_name ?? undefined,
		category_id: p.category_id,
		confidence: p.confidence,
		moving_avg_price: p.est_value,
		destination_bin: p.bin ? [p.bin.x, p.bin.y, p.bin.z] : null,
		brickognize_preview_url: p.preview_url,
		distributed_at: p.recorded_at ?? null
	};
}

function newerCapturedCrop(
	existing: KnownObjectData | undefined,
	incoming: KnownObjectData
): Pick<KnownObjectData, 'latest_captured_crop' | 'latest_captured_crop_ts'> {
	const incoming_ts = incoming.latest_captured_crop_ts;
	const existing_ts = existing?.latest_captured_crop_ts;
	if (
		incoming.latest_captured_crop &&
		((typeof incoming_ts === 'number' && (existing_ts == null || incoming_ts >= existing_ts)) ||
			!existing?.latest_captured_crop)
	) {
		return {
			latest_captured_crop: incoming.latest_captured_crop,
			latest_captured_crop_ts: incoming_ts ?? existing_ts ?? null
		};
	}
	return {
		latest_captured_crop: existing?.latest_captured_crop ?? incoming.latest_captured_crop,
		latest_captured_crop_ts: existing_ts ?? incoming_ts
	};
}

// Field-preserving merge: incoming WS events are partial-ish (slimmed crops,
// zone fields only present while live), so a naive replace loses data.
export function mergeKnownObject(
	existing: KnownObjectData | undefined,
	incoming: KnownObjectData
): KnownObjectData {
	if (!existing) return incoming;
	const captured_crop = newerCapturedCrop(existing, incoming);
	return {
		...existing,
		...incoming,
		first_carousel_seen_ts: incoming.first_carousel_seen_ts ?? existing.first_carousel_seen_ts,
		first_carousel_seen_angle_deg:
			incoming.first_carousel_seen_angle_deg ?? existing.first_carousel_seen_angle_deg,
		classification_channel_zone_state:
			incoming.classification_channel_zone_state ?? existing.classification_channel_zone_state,
		classification_channel_zone_center_deg:
			incoming.classification_channel_zone_center_deg ??
			existing.classification_channel_zone_center_deg,
		classification_channel_zone_half_width_deg:
			incoming.classification_channel_zone_half_width_deg ??
			existing.classification_channel_zone_half_width_deg,
		classification_channel_exit_offset_deg:
			incoming.classification_channel_exit_offset_deg ??
			existing.classification_channel_exit_offset_deg,
		...captured_crop,
		thumbnail: incoming.thumbnail ?? existing.thumbnail,
		top_image: incoming.top_image ?? existing.top_image,
		bottom_image: incoming.bottom_image ?? existing.bottom_image,
		drop_snapshot: incoming.drop_snapshot ?? existing.drop_snapshot,
		brickognize_preview_url: incoming.brickognize_preview_url ?? existing.brickognize_preview_url,
		brickognize_source_view: incoming.brickognize_source_view ?? existing.brickognize_source_view,
		recognition_used_crop_ts: incoming.recognition_used_crop_ts?.length
			? incoming.recognition_used_crop_ts
			: existing.recognition_used_crop_ts
	};
}

function recencyTs(p: Piece): number {
	if (p.ws) return p.ws.updated_at ?? p.ws.created_at ?? 0;
	return p.recorded_at ?? p.seen_at ?? 0;
}

function demote(p: Piece): Piece {
	if (!p.ws) return p;
	return { ...p, origin: 'rest', ws: null };
}

// One store, many consumers: the RecentObjects dropdown, the records page's
// live rows, and the tracked detail page all read the same per-machine entry
// list. MachineManager feeds WS events in; components feed REST fills in.
class PieceStore {
	private byMachine = $state(new Map<string, Piece[]>());
	private rest_filled = new Set<string>();

	entriesFor(machineId: string | null | undefined): Piece[] {
		if (!machineId) return [];
		return this.byMachine.get(machineId) ?? [];
	}

	needsRestFill(machineId: string): boolean {
		return !this.rest_filled.has(machineId);
	}

	markRestFilled(machineId: string): void {
		this.rest_filled.add(machineId);
	}

	upsertFromWs(machineId: string, obj: KnownObjectData): void {
		const list = this.entriesFor(machineId);
		// Aborted = cycle torn down before any result; nothing durable exists and
		// nothing more will arrive. Remove outright.
		if (obj.aborted) {
			if (!list.some((p) => p.uuid === obj.uuid)) return;
			this.publish(
				machineId,
				list.filter((p) => p.uuid !== obj.uuid)
			);
			return;
		}
		const idx = list.findIndex((p) => p.uuid === obj.uuid);
		const existing = idx >= 0 ? list[idx] : undefined;
		const merged = pieceFromKnownObject(mergeKnownObject(existing?.ws ?? undefined, obj));
		if (existing) {
			merged.run_id = merged.run_id ?? existing.run_id;
			merged.recorded_at = merged.recorded_at ?? existing.recorded_at;
			merged.est_value = merged.est_value ?? existing.est_value;
			merged.preview_url = merged.preview_url ?? existing.preview_url;
			merged.has_images = merged.has_images || existing.has_images;
		}
		let next: Piece[];
		if (idx >= 0) {
			next = [...list];
			next[idx] = merged;
		} else {
			next = [merged, ...list];
		}
		this.publish(machineId, this.enforceCaps(next));
	}

	upsertFromRest(machineId: string, summaries: PieceSummary[]): void {
		if (summaries.length === 0) return;
		const list = this.entriesFor(machineId);
		const by_uuid = new Map(list.map((p, i) => [p.uuid, i]));
		const next = [...list];
		for (const s of summaries) {
			const idx = by_uuid.get(s.uuid);
			if (idx === undefined) {
				by_uuid.set(s.uuid, next.length);
				next.push(pieceFromSummary(s));
				continue;
			}
			const existing = next[idx];
			if (existing.ws) {
				// The live payload is fresher — only backfill durable-only fields.
				next[idx] = {
					...existing,
					run_id: existing.run_id ?? s.run_id ?? null,
					recorded_at: existing.recorded_at ?? s.recorded_at ?? null,
					est_value: existing.est_value ?? s.est_value ?? null,
					preview_url: existing.preview_url ?? s.preview_url ?? null,
					has_images: existing.has_images || Boolean(s.has_images)
				};
			} else {
				next[idx] = pieceFromSummary(s);
			}
		}
		this.publish(machineId, this.enforceCaps(next));
	}

	// Clear-on-homing semantics: live entries can't survive a re-home (their
	// cycles are torn down), but completed ones are durable history — demote
	// them to rest summaries instead of wiping like the old ring did.
	clearWsEntries(machineId: string): void {
		const list = this.entriesFor(machineId);
		if (!list.some((p) => p.ws)) return;
		const next: Piece[] = [];
		for (const p of list) {
			if (!p.ws) {
				next.push(p);
				continue;
			}
			if (isTerminalPiece(p)) next.push(demote(p));
		}
		this.publish(machineId, next);
	}

	private enforceCaps(list: Piece[]): Piece[] {
		let next = list;
		const ws_entries = next.filter((p) => p.ws);
		if (ws_entries.length > WS_ENTRY_LIMIT) {
			const evict = new Set(
				ws_entries
					.sort((a, b) => recencyTs(b) - recencyTs(a))
					.slice(WS_ENTRY_LIMIT)
					.map((p) => p.uuid)
			);
			next = next.map((p) => (evict.has(p.uuid) ? demote(p) : p));
		}
		if (next.length > TOTAL_ENTRY_LIMIT) {
			next = [...next].sort((a, b) => recencyTs(b) - recencyTs(a)).slice(0, TOTAL_ENTRY_LIMIT);
		}
		return next;
	}

	private publish(machineId: string, list: Piece[]): void {
		const updated = new Map(this.byMachine);
		updated.set(machineId, list);
		this.byMachine = updated;
	}
}

export const pieceStore = new PieceStore();
