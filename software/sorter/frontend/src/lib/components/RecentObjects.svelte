<script lang="ts">
	import { getMachineContext } from '$lib/machines/context';
	import { untrack } from 'svelte';
	import { Wand2 } from 'lucide-svelte';
	import type { KnownObjectData } from '$lib/api/events';
	import Spinner from './Spinner.svelte';
	import Modal from './Modal.svelte';
	import PieceCorrection from './PieceCorrection.svelte';
	import PieceStatusBadge from './PieceStatusBadge.svelte';
	import { fetchPieceImageState, type DisplayImage } from './records/piece-images';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { LEGO_COLORS, type LegoColor } from '$lib/lego-colors';
	import {
		pieceStore,
		pieceToKnownObjectView,
		pieceToSummary,
		isTerminalPiece,
		type Piece,
		type PieceSummary,
		type PiecesListResponse
	} from '$lib/pieces';

	// 'resolved' = the classification outcome is known (any status, good or bad)
	// but the piece hasn't been delivered yet. The chip for it comes from
	// PieceStatusBadge so a failed/unidentified piece can never read as the green
	// success chip — the green is gated on classification_status === 'classified'.
	type LifecyclePhase = 'tracking' | 'capturing' | 'resolved' | 'distributed';

	const MAX_DELIVERED_PIECES = 8;
	const RECENT_TERMINAL_DEDUPE_WINDOW_S = 15;
	const C4_DROP_ANGLE_DEG = 30;
	// A piece that landed on C4 emits a KnownObject (with a crop) the instant it
	// is photographed, but only gets a terminal classification_status once it
	// reaches distribution. If its cycle is torn down first — machine stop,
	// backend restart, or the state machine reset mid-capture — the object
	// freezes in the 'capturing'/'tracking' phase and never receives another
	// event, so it would otherwise sit in this list forever. C4 processes one
	// piece at a time: the live piece updates every frame and flips to
	// 'resolved' within seconds, so any OLDER pre-classification piece that
	// has had no event for this long has been abandoned and is dropped.
	const STALE_CAPTURING_S = 15;
	// A piece that classified but never reached distribution stops emitting
	// events and would otherwise sit in the active list forever. The backend
	// reaps these (marking them `dead`, which removes them from the buffer)
	// after ~30s of silence; this is the UI backstop for when that signal never
	// arrives (e.g. backend wedged). Set slightly above the backend timeout so
	// the authoritative `dead` event normally wins first.
	const STALE_CLASSIFIED_S = 35;
	const REST_FILL_LIMIT = 32;

	const ctx = getMachineContext();
	sortingProfileStore.load();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	const machineId = $derived(ctx.machine?.identity?.machine_id ?? null);
	const storePieces = $derived(pieceStore.entriesFor(machineId));

	// --- Brickognize correction modal -------------------------------------
	// The recent-piece cards are links to the detail page; opening the correction
	// UI must not navigate. A small wand button on correctable cards opens the
	// shared PieceCorrection component in a modal. The summary is derived live
	// from the store so a correction updates in place.
	let correctingUuid = $state<string | null>(null);
	const correctingPiece = $derived.by<Piece | null>(() => {
		if (!correctingUuid) return null;
		return storePieces.find((x) => x.uuid === correctingUuid) ?? null;
	});
	const correctingSummary = $derived(
		correctingPiece ? pieceToSummary(correctingPiece) : null
	);
	const correctionOpen = $derived(correctingSummary !== null);

	function openCorrection(uuid: string, event: MouseEvent) {
		event.preventDefault();
		event.stopPropagation();
		correctingUuid = uuid;
	}

	function onCorrectionUpdated(summary: PieceSummary) {
		if (machineId) pieceStore.upsertFromRest(machineId, [summary]);
	}

	// The C4 burst crops we captured for the piece being corrected — shown in the
	// modal alongside the Brickognize prediction. Fetched once per opened piece.
	// `correctingUuid` is the ONLY thing this effect should react to; everything
	// else the body touches (correctingSummary, effectiveBase() -> ctx.machine)
	// must stay inside `untrack` or the effect re-fires — and resets/reloads the
	// gallery — every time that unrelated reactive state changes (e.g. the
	// machine context ticking on a heartbeat), not just when the piece changes.
	let modalBurstImages = $state<DisplayImage[]>([]);
	let modalImagesLoading = $state(false);
	let modalImagesRequestId = 0;
	$effect(() => {
		const uuid = correctingUuid;
		untrack(() => {
			if (!uuid) {
				modalBurstImages = [];
				modalImagesLoading = false;
				return;
			}
			const seen_at = correctingSummary?.seen_at ?? null;
			const base = effectiveBase();
			const requestId = ++modalImagesRequestId;
			modalBurstImages = [];
			modalImagesLoading = true;
			void fetchPieceImageState(base, uuid, seen_at).then((state) => {
				if (requestId !== modalImagesRequestId) return;
				modalBurstImages = state.images.filter((img) => img.source === 'c4_burst');
				modalImagesLoading = false;
			});
		});
	});

	// Initial fill: the backend no longer replays recent pieces on WS connect —
	// the durable records API is the source for "what happened before this
	// session". One fetch per machine per app session.
	$effect(() => {
		const machine_id = machineId;
		if (!machine_id || !pieceStore.needsRestFill(machine_id)) return;
		pieceStore.markRestFilled(machine_id);
		void fetch(`${effectiveBase()}/api/pieces?limit=${REST_FILL_LIMIT}`)
			.then(async (res) => {
				if (!res.ok) return;
				const json = (await res.json()) as PiecesListResponse;
				pieceStore.upsertFromRest(machine_id, json.items ?? []);
			})
			.catch(() => {
				// Silent — the list just starts empty until live events arrive.
			});
	});

	// C4 gate: live entries only show once observed on the classification
	// channel. Rest-origin rows are EXEMPT — they are already-completed pieces
	// from the durable store and don't carry first_carousel_seen_ts.
	function inRecentView(p: Piece): boolean {
		if (p.dead || p.ws?.aborted) return false;
		if (p.ws) return p.ws.first_carousel_seen_ts != null;
		return true;
	}

	function hasLocalPreview(obj: KnownObjectData): boolean {
		return Boolean(
			obj.latest_captured_crop ||
				obj.thumbnail ||
				obj.top_image ||
				obj.bottom_image ||
				obj.drop_snapshot
		);
	}

	function hasCapturingEvidence(obj: KnownObjectData): boolean {
		// Anything proving the capture/classify pipeline has engaged: a snap
		// timestamp, a locally-stored crop or thumbnail, or any part data.
		return Boolean(
			obj.carousel_snapping_started_at ||
				obj.classified_at ||
				obj.part_id ||
				hasLocalPreview(obj)
		);
	}

	function isResolvedStatus(status: string | null | undefined): boolean {
		return (
			status === 'classified' ||
			status === 'failed' ||
			status === 'unknown' ||
			status === 'not_found' ||
			status === 'multi_drop_fail'
		);
	}

	function lifecyclePhase(obj: KnownObjectData): LifecyclePhase {
		// "Distributing" (in motion) still renders as resolved. Only fully-
		// delivered pieces flip to 'distributed'.
		if (isTerminalObject(obj)) return 'distributed';
		if (isResolvedStatus(obj.classification_status) || obj.classified_at) {
			return 'resolved';
		}
		if (hasCapturingEvidence(obj)) return 'capturing';
		// Reliably tracked by the carousel tracker but no capture has started
		// yet — show the piece as soon as we have an identity for it.
		if (obj.tracked_global_id !== null && obj.tracked_global_id !== undefined) {
			return 'tracking';
		}
		return 'capturing';
	}

	function isTerminalObject(obj: KnownObjectData): boolean {
		return obj.stage === 'distributed' || obj.distributed_at != null;
	}

	function isUnresolvedTerminal(obj: KnownObjectData): boolean {
		return (
			obj.classification_status === 'failed' ||
			obj.classification_status === 'unknown' ||
			obj.classification_status === 'not_found' ||
			obj.classification_status === 'multi_drop_fail'
		);
	}

	function hasTerminalEvidence(p: Piece): boolean {
		const obj = p.ws;
		// Rest-origin rows always qualify — they are durable records; the card
		// renders a neutral placeholder when no preview exists.
		if (!obj) return true;
		if (!isTerminalObject(obj)) return true;
		if (!isUnresolvedTerminal(obj)) return true;
		return Boolean(
			obj.latest_captured_crop ||
				obj.top_image ||
				obj.bottom_image ||
				(obj.thumbnail && obj.classified_at)
		);
	}

	function physicalPieceKey(p: Piece): string {
		const gid = p.ws?.tracked_global_id;
		return gid !== null && gid !== undefined ? `track:${gid}` : `uuid:${p.uuid}`;
	}

	function lastEventTs(p: Piece): number {
		const obj = pieceToKnownObjectView(p);
		return obj.updated_at ?? obj.created_at ?? 0;
	}

	function terminalTs(p: Piece): number {
		const obj = pieceToKnownObjectView(p);
		return obj.distributed_at ?? obj.updated_at ?? obj.classified_at ?? obj.created_at ?? 0;
	}

	function c4ArrivalTs(obj: KnownObjectData): number {
		return obj.first_carousel_seen_ts ?? obj.carousel_detected_confirmed_at ?? obj.created_at ?? 0;
	}

	function normalizeDeg(value: number): number {
		const normalized = value % 360;
		return normalized < 0 ? normalized + 360 : normalized;
	}

	function circularDiffDeg(a: number, b: number): number {
		return ((normalizeDeg(a) - normalizeDeg(b) + 540) % 360) - 180;
	}

	function c4ExitApproachOffset(obj: KnownObjectData): number | null {
		const exit_offset = obj.classification_channel_exit_offset_deg;
		if (typeof exit_offset === 'number' && Number.isFinite(exit_offset)) return exit_offset;
		const center = obj.classification_channel_zone_center_deg;
		if (typeof center !== 'number' || !Number.isFinite(center)) return null;
		// Negative means still approaching the configured drop/exit line;
		// values closer to zero are physically closer to being distributed.
		return circularDiffDeg(center, C4_DROP_ANGLE_DEG);
	}

	function dedupeByPhysicalPiece(pieces: Piece[]): Piece[] {
		const seen = new Set<string>();
		const deduped: Piece[] = [];
		for (const p of pieces) {
			const key = physicalPieceKey(p);
			if (seen.has(key)) continue;
			seen.add(key);
			deduped.push(p);
		}
		return deduped;
	}

	function sortActiveC4Pieces(a: Piece, b: Piece): number {
		const aOffset = a.ws ? c4ExitApproachOffset(a.ws) : null;
		const bOffset = b.ws ? c4ExitApproachOffset(b.ws) : null;
		if (aOffset !== null && bOffset !== null && aOffset !== bOffset) {
			return aOffset - bOffset;
		}
		const arrivalDiff = (b.ws ? c4ArrivalTs(b.ws) : 0) - (a.ws ? c4ArrivalTs(a.ws) : 0);
		if (arrivalDiff !== 0) return arrivalDiff;
		return lastEventTs(b) - lastEventTs(a);
	}

	// Tick loop so relative timestamps refresh and stale pieces drop without new
	// events.
	let now_tick = $state(0);
	$effect(() => {
		const id = setInterval(() => (now_tick += 1), 1000);
		return () => clearInterval(id);
	});

	const activeOnC4 = $derived.by(() => {
		// Re-evaluate on the 1s tick so abandoned (frozen) pieces drop out of the
		// list even when no new events are arriving.
		void now_tick;
		const all = storePieces.filter(inRecentView);
		// If a terminal event and a stale active split briefly coexist, keep
		// the terminal row and suppress the old active identity.
		const recent_terminal_keys = new Set<string>();
		const now_s = Date.now() / 1000;
		for (const p of all) {
			if (!isTerminalPiece(p)) continue;
			const ts = terminalTs(p);
			if (now_s - ts > RECENT_TERMINAL_DEDUPE_WINDOW_S) continue;
			recent_terminal_keys.add(physicalPieceKey(p));
		}

		// Only live (ws-origin) entries can be active on the channel.
		const freshest_first = all
			.filter((p) => p.ws != null && !isTerminalPiece(p))
			.filter((p) => !recent_terminal_keys.has(physicalPieceKey(p)))
			.sort((a, b) => lastEventTs(b) - lastEventTs(a));

		// Drop orphaned pre-classification pieces (see STALE_CAPTURING_S). The
		// freshest active piece is always kept — that's the one currently on the
		// channel, which may legitimately sit pre-classification for a few
		// seconds while the identification requests run.
		const deduped = dedupeByPhysicalPiece(freshest_first);
		const live = deduped.filter((p, i) => {
			const phase = lifecyclePhase(p.ws as KnownObjectData);
			const stale_s = now_s - lastEventTs(p);
			if (phase === 'capturing' || phase === 'tracking') {
				return i === 0 || stale_s <= STALE_CAPTURING_S;
			}
			// Resolved but not yet distributed — drop once it has gone silent
			// past the backstop window (see STALE_CLASSIFIED_S) so a stuck piece
			// can't sit in the active list forever.
			return stale_s <= STALE_CLASSIFIED_S;
		});

		return live.sort(sortActiveC4Pieces);
	});

	const deliveredHistory = $derived.by(() => {
		const freshest_first = storePieces
			.filter(inRecentView)
			.filter(isTerminalPiece)
			.filter(hasTerminalEvidence)
			.sort((a, b) => terminalTs(b) - terminalTs(a));
		// Newest terminal piece sits directly under the distributed line.
		return dedupeByPhysicalPiece(freshest_first).slice(0, MAX_DELIVERED_PIECES);
	});

	function dataImageUrl(payload: string | null | undefined): string | null {
		return payload ? `data:image/jpeg;base64,${payload}` : null;
	}

	// --- Recognition-view cycling -----------------------------------------
	// The live piece entries carry only `latest_captured_crop`. The full set of
	// captured crops (every C4 burst frame) is
	// persisted to disk by piece_image_store and served as individual JPEGs via
	// GET /api/pieces/{uuid}/images{,/<id>} — durable across eviction/restart and
	// browser-cached (immutable), so hover works even for pieces that have
	// already left the machine. While a piece is still being recognized we poll
	// that endpoint and flash through every view it has so far, so the
	// operator sees the burst frames animate in place instead of a single frozen
	// crop. When the result lands we keep flashing for one full pass before
	// settling on the reference/stock photo. The classification TEXT
	// updates independently and immediately off the socket; only the image well
	// waits for the pass to finish.
	const CYCLE_MS = 300;
	const FETCH_MS = 600;
	const MIN_FINISH_MS = 1200; // keep flashing at least this long after the result
	const MAX_FINISH_MS = 12000; // safety cap so a card can never flash forever
	const NO_IMG_GRACE_MS = 1500; // give up waiting for views if none ever load

	type CycleAnim = {
		raw: number;
		classified_raw: number | null;
		classified_ms: number;
		settled: boolean;
	};

	function isResultKnown(obj: KnownObjectData): boolean {
		return isResolvedStatus(obj.classification_status) || Boolean(obj.classified_at);
	}

	type CycleImage = { src: string };

	let cycleTick = $state(0);
	let hoverUuid = $state<string | null>(null);
	let imagesByUuid = $state<Record<string, CycleImage[]>>({});
	let anim = $state<Record<string, CycleAnim>>({});
	const lastFetchMs: Record<string, number> = {};
	const fetchingUuids = new Set<string>();

	async function fetchImages(uuid: string): Promise<void> {
		if (fetchingUuids.has(uuid)) return;
		fetchingUuids.add(uuid);
		lastFetchMs[uuid] = Date.now();
		try {
			const base = effectiveBase();
			const res = await fetch(`${base}/api/pieces/${encodeURIComponent(uuid)}/images`);
			if (!res.ok) return;
			const env = (await res.json()) as {
				images?: { id: number; available_locally?: boolean }[];
			};
			const imgs = (env.images ?? [])
				.filter((r) => r.available_locally !== false)
				.map((r): CycleImage => ({
					src: `${base}/api/pieces/${encodeURIComponent(uuid)}/images/${r.id}`
				}));
			// Plus the piece-link model's USED picks (fused into the applied
			// request) — the confident upstream views of this same piece. The
			// rest of its guesses stay off the hover.
			try {
				const linkRes = await fetch(
					`${base}/api/pieces/${encodeURIComponent(uuid)}/link-images`
				);
				if (linkRes.ok) {
					const linkEnv = (await linkRes.json()) as {
						images?: { id: number; used?: boolean; available_locally?: boolean }[];
					};
					for (const r of linkEnv.images ?? []) {
						if (r.used && r.available_locally !== false) {
							imgs.push({
								src: `${base}/api/pieces/${encodeURIComponent(uuid)}/link-images/${r.id}`
							});
						}
					}
				}
			} catch {
				// burst-only hover is fine
			}
			if (imgs.length > 0) imagesByUuid = { ...imagesByUuid, [uuid]: imgs };
		} catch {
			// Silent — the card just keeps showing the captured crop.
		} finally {
			fetchingUuids.delete(uuid);
		}
	}

	function startHover(uuid: string): void {
		hoverUuid = uuid;
		void fetchImages(uuid);
	}
	function endHover(): void {
		hoverUuid = null;
	}

	function cycleStep(now_ms: number): void {
		for (const p of activeOnC4) {
			const obj = p.ws;
			if (!obj) continue;
			const uuid = p.uuid;
			const result_known = isResultKnown(obj);
			let e = anim[uuid];
			if (!e) {
				// A piece first seen already resolved never flashed for us — show
				// its stock photo straight away rather than animating after the fact.
				anim[uuid] = {
					raw: 0,
					classified_raw: null,
					classified_ms: 0,
					settled: result_known
				};
				e = anim[uuid];
			}
			if (e.settled) continue;
			const imgs = imagesByUuid[uuid] ?? [];
			if (now_ms - (lastFetchMs[uuid] ?? 0) > FETCH_MS && !fetchingUuids.has(uuid)) {
				void fetchImages(uuid);
			}
			if (result_known && e.classified_raw === null) {
				e.classified_raw = e.raw;
				e.classified_ms = now_ms;
			}
			e.raw += 1;
			if (result_known && e.classified_raw !== null) {
				const pass_done = imgs.length > 0 && e.raw - e.classified_raw >= imgs.length;
				const min_elapsed = now_ms - e.classified_ms >= MIN_FINISH_MS;
				const max_elapsed = now_ms - e.classified_ms >= MAX_FINISH_MS;
				const no_imgs = imgs.length === 0 && now_ms - e.classified_ms >= NO_IMG_GRACE_MS;
				if ((pass_done && min_elapsed) || max_elapsed || no_imgs) e.settled = true;
			}
		}
		// Prune state for pieces that have aged out of the store.
		const known = new Set(storePieces.map((p) => p.uuid));
		for (const k of Object.keys(anim)) if (!known.has(k)) delete anim[k];
		for (const k of Object.keys(imagesByUuid)) if (!known.has(k)) delete imagesByUuid[k];
		for (const k of Object.keys(lastFetchMs)) if (!known.has(k)) delete lastFetchMs[k];
	}

	$effect(() => {
		const id = setInterval(() => {
			cycleTick += 1;
			cycleStep(Date.now());
		}, CYCLE_MS);
		return () => clearInterval(id);
	});

	// What the image well shows: a flashing recognition view while the piece is
	// being recognized (and during the post-result finish pass), the hover scrub
	// when the operator points at it, otherwise the base/stock photo.
	function viewFor(
		obj: KnownObjectData,
		phase: LifecyclePhase,
		base_src: string | null
	): { src: string | null; cycling: boolean } {
		const imgs = imagesByUuid[obj.uuid] ?? [];
		if (hoverUuid === obj.uuid && imgs.length > 0) {
			const img = imgs[cycleTick % imgs.length];
			return { src: img.src, cycling: true };
		}
		if (phase === 'distributed') return { src: base_src, cycling: false };
		const e = anim[obj.uuid];
		if (e && !e.settled && imgs.length > 0) {
			const img = imgs[e.raw % imgs.length];
			return { src: img.src, cycling: true };
		}
		return { src: base_src, cycling: false };
	}

	function capturedCropUrl(obj: KnownObjectData, phase: LifecyclePhase): string | null {
		// Prefer the newest object crop; full-frame/drop snapshots are only a
		// final fallback once no crop-like evidence exists.
		const crop_like =
			dataImageUrl(obj.latest_captured_crop) ??
			dataImageUrl(obj.top_image) ??
			dataImageUrl(obj.bottom_image);
		if (crop_like) return crop_like;
		if (phase === 'tracking' || phase === 'capturing') return null;
		return (
			dataImageUrl(obj.thumbnail) ??
			dataImageUrl(obj.drop_snapshot)
		);
	}

	function formatBin(bin: [unknown, unknown, unknown]): string {
		return `L${bin[0]} · S${bin[1]} · B${bin[2]}`;
	}

	function confidenceClass(conf: number): string {
		// 4-tier grading per spec. There is no dedicated orange brand token, so
		// 80-89 and 60-79 both use the warning amber — 60-79 uses a dimmer
		// opacity to visually distinguish "marginal" from "good".
		const pct = conf * 100;
		if (pct >= 90) return 'text-success';
		if (pct >= 80) return 'text-warning';
		if (pct >= 60) return 'text-warning/70';
		return 'text-danger';
	}

	// BrickLink moving-average price (USD) from the local parts.db. Sub-dollar
	// pieces (most bricks) get an extra decimal so they don't all collapse to
	// "$0.00"; a dollar and up reads as plain currency.
	function formatPrice(price: number): string {
		return price >= 0.01 ? `$${price.toFixed(2)}` : `$${price.toFixed(3)}`;
	}

	// First-release year for the card badge: Rebrickable year_from, falling back
	// to the BrickLink release year (used for printed parts / minifigs). Null when
	// unknown. Pulled straight off the piece_metadata blob on the event.
	function yearOf(obj: KnownObjectData): number | null {
		const md = obj.piece_metadata as Record<string, unknown> | null | undefined;
		if (!md) return null;
		const bl = md.bricklink as Record<string, unknown> | null | undefined;
		const y = (md.year_from as number | undefined) ?? (bl?.year_released as number | undefined);
		return typeof y === 'number' && y > 0 ? y : null;
	}

	function phaseChip(phase: LifecyclePhase): { label: string; cls: string } {
		// Sharp-edged chip, border + faint tinted bg + solid text. No rounded-*.
		// 'resolved' never lands here — it renders as PieceStatusBadge instead.
		if (phase === 'tracking')
			return { label: 'Tracking', cls: 'border-text-muted bg-text-muted/10 text-text-muted' };
		if (phase === 'capturing')
			return { label: 'Capturing', cls: 'border-primary bg-primary/10 text-primary' };
		return { label: 'Distributed', cls: 'border-border bg-surface text-text-muted' };
	}

	// Normalize a color id or name to a LEGO_COLORS entry. Brickognize and
	// BrickLink both use slug-ish ids (e.g. "white", "light-bluish-gray"), and
	// `color_name` is the canonical display name. Try id first, fall back to
	// name match (case-insensitive).
	// --- Multi-drop grouping ----------------------------------------------
	// A multi drop rejects every piece involved, and each one used to get its own
	// full-size red card — a wall of alarm for what is physically ONE event. Runs
	// of adjacent multi-drop pieces (the list is already time-ordered, so a run is
	// one drop) collapse into a single subdued card with the crops stacked.
	type Row =
		| { kind: 'piece'; piece: Piece }
		| { kind: 'multi_drop'; pieces: Piece[] };

	const MULTI_DROP_STACK_MAX = 4;

	function isMultiDropPiece(p: Piece): boolean {
		return pieceToKnownObjectView(p).classification_status === 'multi_drop_fail';
	}

	function groupRows(pieces: Piece[]): Row[] {
		const rows: Row[] = [];
		for (const p of pieces) {
			if (!isMultiDropPiece(p)) {
				rows.push({ kind: 'piece', piece: p });
				continue;
			}
			const last = rows[rows.length - 1];
			if (last && last.kind === 'multi_drop') last.pieces.push(p);
			else rows.push({ kind: 'multi_drop', pieces: [p] });
		}
		return rows;
	}

	const activeRows = $derived(groupRows(activeOnC4));
	const deliveredRows = $derived(groupRows(deliveredHistory));

	function rowKey(row: Row): string {
		return row.kind === 'piece' ? row.piece.uuid : `md:${row.pieces[0].uuid}`;
	}

	function multiDropThumb(p: Piece): string | null {
		const obj = pieceToKnownObjectView(p);
		return capturedCropUrl(obj, lifecyclePhase(obj));
	}

	function lookupLegoColor(
		color_id: string | null | undefined,
		color_name: string | null | undefined
	): LegoColor | null {
		if (color_id) {
			const by_id = LEGO_COLORS.find((c) => c.id === color_id);
			if (by_id) return by_id;
		}
		if (color_name) {
			const lower = color_name.toLowerCase();
			const by_name = LEGO_COLORS.find((c) => c.name.toLowerCase() === lower);
			if (by_name) return by_name;
		}
		return null;
	}

</script>

{#snippet pieceCard(p: Piece)}
	{@const obj = pieceToKnownObjectView(p)}
	{@const phase = lifecyclePhase(obj)}
	{@const captured = capturedCropUrl(obj, phase)}
	{@const preview = obj.brickognize_preview_url ?? null}
	{@const reference_src = preview}
	{@const cat_name = obj.category_id
		? sortingProfileStore.getCategoryName(obj.category_id)
		: null}
	{@const is_unknown =
		obj.classification_status === 'unknown' ||
		obj.classification_status === 'not_found'}
	{@const is_failed =
		obj.classification_status === 'failed' || Boolean(obj.request_failed)}
	{@const is_multi_drop = obj.classification_status === 'multi_drop_fail'}
	{@const is_too_big = Boolean(obj.too_big) || Boolean(obj.too_big_for_layer)}
	{@const too_big_label = obj.too_big_for_layer ? 'Too big for layer' : 'Too big'}
	{@const is_classified_ok = !is_unknown && !is_multi_drop && Boolean(reference_src)}
	{@const ts =
		obj.distributed_at ??
		obj.classified_at ??
		obj.first_carousel_seen_ts ??
		obj.updated_at ??
		obj.created_at}

	{@const lego_color =
		!is_unknown && !is_multi_drop && obj.color_name && obj.color_name !== 'Any Color'
			? lookupLegoColor(obj.color_id, obj.color_name)
			: null}
	<!-- Brickognize supplies `part_name` whenever it has a hit; fall back to
	     the part id when there's no name. -->
	{@const resolved_name = obj.part_name ?? null}
	{@const has_name = Boolean(resolved_name) && !is_unknown && !is_multi_drop}
	{@const primary_text = is_multi_drop
		? 'Multi drop — rejected'
		: is_failed
			? 'ID failed'
			: is_unknown
				? obj.classification_status === 'not_found'
					? 'Not recognized'
					: 'Unknown piece'
				: has_name
					? resolved_name!
					: (obj.part_id ?? obj.uuid.slice(0, 8))}
	{@const primary_class = is_multi_drop || is_failed
		? 'text-danger'
		: is_unknown
			? 'text-text-muted'
			: 'text-text'}

	{@const base_src = is_classified_ok ? reference_src : captured}
	<!-- Flash through every recognition view (burst frames)
	     while the piece is being recognized and during the finish pass; hover
	     scrubs the same views. -->
	{@const view = viewFor(obj, phase, base_src)}
	{@const cycle_src = view.src}
	{@const show_cycle = view.cycling && cycle_src != null && cycle_src !== base_src}

	<a
		href={`/tracked/${obj.uuid}`}
		class="block border border-border bg-bg transition-colors hover:border-primary/70"
		onmouseenter={() => startHover(obj.uuid)}
		onmouseleave={endHover}
	>
		<div class="flex items-start gap-3 p-2">
			<!-- Primary image well — flashes through every recognition view while
			     the piece is being recognized; hover scrubs the same views. -->
			<div class="relative h-20 w-20 flex-shrink-0 border border-border bg-white">
				{#if base_src || cycle_src}
					{#if base_src}
						<img
							src={base_src}
							alt="piece"
							class="absolute inset-0 h-full w-full object-contain transition-opacity duration-150 {show_cycle
								? 'opacity-0'
								: 'opacity-100'}"
						/>
					{/if}
					{#if cycle_src}
						<img
							src={cycle_src}
							alt="recognition view"
							class="absolute inset-0 h-full w-full object-contain transition-opacity duration-150 {show_cycle
								? 'opacity-100'
								: 'opacity-0'}"
						/>
					{/if}
				{:else if phase === 'distributed'}
					<!-- Terminal piece with nothing to show (e.g. a durable summary of an
					     unidentified piece) — a spinner here would imply waiting. -->
					<div class="flex h-full w-full items-center justify-center text-xs text-text-muted">
						no image
					</div>
				{:else}
					<div class="flex h-full w-full items-center justify-center">
						<Spinner />
					</div>
				{/if}
			</div>

			<div class="flex min-w-0 flex-1 flex-col gap-1">
				<div class="flex items-baseline justify-between gap-2">
					<span class="truncate text-sm font-semibold {primary_class}">
						{primary_text}
					</span>
					<div class="flex flex-shrink-0 items-center gap-2">
						{#if typeof obj.confidence === 'number' && !is_unknown && !is_multi_drop}
							<span class="text-sm font-semibold tabular-nums {confidenceClass(obj.confidence)}">
								{(obj.confidence * 100).toFixed(0)}%
							</span>
						{/if}
						{#if p.correctable}
							{@const submittedCount =
								(p.part_feedback_submitted ? 1 : 0) + (p.color_feedback_submitted ? 1 : 0)}
							<button
								type="button"
								onclick={(e) => openCorrection(obj.uuid, e)}
								class="inline-flex items-center transition-colors {submittedCount === 2
									? 'text-success'
									: submittedCount === 1
										? 'text-warning'
										: 'text-text-muted hover:text-primary'}"
								title={submittedCount === 2
									? 'Correction sent to Brickognize (2/2)'
									: submittedCount === 1
										? 'Correction sent to Brickognize (1/2) — click to finish'
										: 'Correct this Brickognize prediction'}
								aria-label="Correct prediction"
							>
								<Wand2 size={14} />
							</button>
						{/if}
					</div>
				</div>

				{#if has_name && obj.part_id}
					<div class="flex items-baseline justify-between gap-2">
						<span class="truncate font-mono text-xs text-text-muted">{obj.part_id}</span>
						{#if typeof obj.moving_avg_price === 'number'}
							<span
								class="flex-shrink-0 text-sm font-semibold tabular-nums text-success"
								title={(obj.piece_metadata as Record<string, unknown> | null | undefined)
									?.price_from_base_mold
									? `Approximate — base mold ${(obj.piece_metadata as Record<string, unknown>).price_from_base_mold} price (no data for this exact print)`
									: 'BrickLink moving-average price (local catalog)'}
							>
								{(obj.piece_metadata as Record<string, unknown> | null | undefined)
									?.price_from_base_mold
									? '≈'
									: ''}{formatPrice(obj.moving_avg_price)}
							</span>
						{/if}
					</div>
				{:else if phase === 'tracking' && !is_unknown && !is_multi_drop}
					<div class="text-xs text-text-muted">Tracked on carousel…</div>
				{:else if phase === 'capturing' && !is_unknown && !is_multi_drop}
					<div class="text-xs text-text-muted">Capturing on C4…</div>
				{/if}

				<div class="mt-0.5 flex flex-wrap items-center gap-1.5">
					<!-- Phase / status chip. The classification outcome renders through
					     the shared badge; the green success chip is impossible for
					     failed/unidentified pieces. -->
					{#if phase === 'resolved' || (phase === 'distributed' && obj.classification_status !== 'classified')}
						<PieceStatusBadge
							status={obj.classification_status}
							requestFailed={Boolean(obj.request_failed)}
						/>
					{:else}
						{@const chip = phaseChip(phase)}
						<span
							class="inline-flex items-center border px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider {chip.cls}"
						>
							{chip.label}
						</span>
					{/if}

					<!-- Too-big chip — recognized piece rerouted to misc for size -->
					{#if is_too_big}
						<span
							class="inline-flex items-center border border-warning/60 bg-warning/[0.12] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-warning"
							title={obj.too_big_for_layer && typeof obj.intended_layer_index === 'number'
								? `Too big for layer ${obj.intended_layer_index + 1} — sent to misc bottom bin`
								: 'Too big — sent to misc bottom bin'}
						>
							{too_big_label}{typeof obj.max_dimension_mm === 'number'
								? ` · ${Math.round(obj.max_dimension_mm)}mm`
								: ''}
						</span>
					{/if}

					<!-- High-value chip — piece rerouted by the profile's price override -->
					{#if obj.high_value_routed}
						<span
							class="inline-flex items-center border border-success/60 bg-success/[0.12] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-success"
							title="Moving-average price cleared the profile's high-value threshold — rerouted to the high-value bin"
						>
							High value
						</span>
					{/if}

					<!-- Not-in-inventory badge — part+color absent from the active .bsx -->
					{#if obj.not_in_inventory === true}
						<span
							class="inline-flex items-center border border-warning/60 bg-warning/[0.12] px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-warning"
							title="This part+color is not in the active BrickLink inventory (.bsx)"
						>
							Not in inventory
						</span>
					{/if}

					<!-- Year badge — first-release year -->
					{#if yearOf(obj) !== null}
						<span
							class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs font-semibold tabular-nums text-text-muted"
							title="First-release year"
						>
							{yearOf(obj)}
						</span>
					{/if}

					<!-- Color chip — sharp-edged, filled with the LEGO hex -->
					{#if lego_color}
						<span
							class="inline-flex items-center border border-border px-1.5 py-0.5 text-xs font-semibold"
							style:background-color={lego_color.hex}
							style:color={lego_color.contrast === 'white' ? '#ffffff' : '#000000'}
						>
							{lego_color.name}
						</span>
					{:else if obj.color_name && obj.color_name !== 'Any Color' && !is_unknown && !is_multi_drop}
						<span class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs text-text-muted">
							{obj.color_name}
						</span>
					{/if}

					<!-- Category (plain, de-emphasized) -->
					{#if cat_name && !is_unknown && !is_multi_drop}
						<span class="text-xs text-text-muted">{cat_name}</span>
					{/if}

					<!-- Bin chip — monospace, neutral surface -->
					{#if obj.destination_bin && phase === 'distributed'}
						<span
							class="ml-auto inline-flex items-center border border-border bg-surface px-1.5 py-0.5 font-mono text-xs tabular-nums text-text"
						>
							{is_unknown || is_multi_drop || is_too_big ? 'discard ' : ''}{formatBin(obj.destination_bin)}
						</span>
					{:else if phase === 'distributed' && (is_unknown || is_multi_drop || is_too_big)}
						<span class="ml-auto inline-flex items-center border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text-muted">
							discard bin
						</span>
					{/if}
				</div>
			</div>
		</div>
	</a>
{/snippet}

{#snippet multiDropCard(pieces: Piece[])}
	{@const first = pieces[0]}
	{@const obj = pieceToKnownObjectView(first)}
	{@const phase = lifecyclePhase(obj)}
	{@const thumbs = pieces.map(multiDropThumb).filter((s) => s !== null) as string[]}
	{@const shown = thumbs.slice(0, MULTI_DROP_STACK_MAX)}
	{@const extra = pieces.length - shown.length}

	<a
		href={`/tracked/${obj.uuid}`}
		class="block border border-border bg-bg transition-colors hover:border-primary/70"
	>
		<div class="flex items-center gap-3 p-2">
			<!-- Crops from the drop, overlapped into one horizontal stack so the
			     whole event reads as a single object rather than N alarming cards. -->
			<div class="flex flex-shrink-0 items-center">
				{#if shown.length > 0}
					{#each shown as src, i}
						<div
							class="relative h-14 w-14 flex-shrink-0 border border-border bg-white {i > 0
								? '-ml-9'
								: ''}"
							style:z-index={shown.length - i}
						>
							<img src={src} alt="rejected piece" class="h-full w-full object-contain" />
						</div>
					{/each}
				{:else}
					<div
						class="flex h-14 w-14 flex-shrink-0 items-center justify-center border border-border bg-white text-xs text-text-muted"
					>
						no image
					</div>
				{/if}
				{#if extra > 0}
					<span class="ml-1 text-xs tabular-nums text-text-muted">+{extra}</span>
				{/if}
			</div>

			<div class="flex min-w-0 flex-1 items-center gap-2">
				<div class="flex min-w-0 flex-col gap-0.5">
					<span class="truncate text-sm text-text-muted">
						Multi drop{pieces.length > 1 ? ` — ${pieces.length} pieces` : ''}
					</span>
					<span
						class="inline-flex w-fit items-center border border-border bg-surface px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-text-muted"
						title="Pieces overlapped on the classification channel and were rejected without identification"
					>
						rejected
					</span>
				</div>

				{#if phase === 'distributed'}
					<span
						class="ml-auto flex-shrink-0 border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text-muted"
					>
						discard bin
					</span>
				{/if}
			</div>
		</div>
	</a>
{/snippet}

<div class="setup-card-shell flex h-full flex-col border">
	<div class="setup-card-header px-3 py-2 text-sm font-medium text-text">Recent Pieces</div>
	<div class="flex-1 overflow-y-auto">
		{#if activeOnC4.length === 0 && deliveredHistory.length === 0}
			<div class="p-3 text-center text-sm text-text-muted">No pieces yet</div>
		{:else}
			<div class="flex flex-col gap-1 p-1">
				<!-- Active C4 pieces: farthest from exit at top, nearest exit above line. -->
				{#each activeRows as row (rowKey(row))}
					{#if row.kind === 'multi_drop'}
						{@render multiDropCard(row.pieces)}
					{:else}
						{@render pieceCard(row.piece)}
					{/if}
				{/each}

				<!-- Exit divider -->
				<div class="flex items-center gap-2 py-1 select-none">
					<div class="h-px flex-1 bg-border"></div>
					<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">distributed</span>
					<div class="h-px flex-1 bg-border"></div>
				</div>

				<!-- Delivered/rejected history: newest-first directly under the line. -->
				{#each deliveredRows as row (rowKey(row))}
					{#if row.kind === 'multi_drop'}
						{@render multiDropCard(row.pieces)}
					{:else}
						{@render pieceCard(row.piece)}
					{/if}
				{/each}
			</div>
		{/if}
	</div>
</div>

<Modal open={correctionOpen} title="Correct prediction" on:close={() => (correctingUuid = null)}>
	{#if correctingSummary}
		{@const capturedSrc =
			dataImageUrl(
				correctingPiece?.ws?.thumbnail ?? correctingPiece?.ws?.latest_captured_crop
			) ?? correctingSummary.preview_url}
		{@const legoColor = lookupLegoColor(
			correctingSummary.color_id,
			correctingSummary.color_name
		)}
		<div class="mb-3 flex items-center gap-3 border-b border-border pb-3">
			{#if capturedSrc}
				<img
					src={capturedSrc}
					alt=""
					class="h-16 w-16 flex-shrink-0 border border-border object-contain"
				/>
			{/if}
			<div class="flex min-w-0 flex-col gap-1">
				<span class="truncate text-sm font-semibold text-text">
					{correctingSummary.part_name ?? correctingSummary.part_id ?? 'Unknown part'}
				</span>
				{#if correctingSummary.part_id && correctingSummary.part_name}
					<span class="font-mono text-xs text-text-muted">{correctingSummary.part_id}</span>
				{/if}
				<span class="inline-flex items-center gap-1.5 text-sm text-text">
					{#if legoColor}
						<span
							class="inline-block h-3.5 w-3.5 flex-shrink-0 border border-border"
							style:background-color={legoColor.hex}
						></span>
					{/if}
					<span>{correctingSummary.color_name ?? '—'}</span>
				</span>
			</div>
			{#if correctingSummary.preview_url}
				<img
					src={correctingSummary.preview_url}
					alt="Brickognize reference"
					title="Brickognize reference image"
					class="ml-auto h-16 w-16 flex-shrink-0 border border-border bg-surface object-contain"
				/>
			{/if}
		</div>

		<!-- The C4 burst crops we captured — never cropped (object-contain), square
		     boxes letterboxed with a transparent bar rather than a solid fill. -->
		{#if modalImagesLoading}
			<div class="mb-3 flex items-center gap-2 text-sm text-text-muted">
				<Spinner size={14} /> Loading captured photos…
			</div>
		{:else if modalBurstImages.length > 0}
			<div class="mb-3 flex flex-col gap-1.5">
				<span class="text-xs font-semibold tracking-wider text-text-muted uppercase">
					Captured photos
				</span>
				<div class="flex flex-wrap gap-1.5">
					{#each modalBurstImages as img (img.src)}
						<div class="h-16 w-16 flex-shrink-0 border border-border">
							<img
								src={img.src}
								alt="captured crop"
								class="h-full w-full object-contain"
								loading="lazy"
							/>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<PieceCorrection
			piece={correctingSummary}
			endpointBase={effectiveBase()}
			onUpdated={onCorrectionUpdated}
		/>
	{/if}
</Modal>
