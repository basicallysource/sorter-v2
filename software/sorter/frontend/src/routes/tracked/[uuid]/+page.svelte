<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/state';
	import { ArrowLeft, ChevronDown, ChevronRight, ExternalLink } from 'lucide-svelte';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import TrackPathComposite from '$lib/components/TrackPathComposite.svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { CarouselMotionSampleData, KnownObjectData } from '$lib/api/events';
	import type { components } from '$lib/api/rest';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';

	type BricklinkPartResponse = components['schemas']['BricklinkPartResponse'];

	const ctx = getMachineContext();
	onMount(() => {
		void sortingProfileStore.load();
	});

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	let uuid = $derived(String(page.params.uuid));

	// Piece lookup — sticky by UUID.
	//
	// recentObjects is the ring buffer the UI maintains from WS events. The
	// manager rebuilds this array on every piece update and drops pending
	// pieces that don't qualify for the gallery (see `shouldKeepRecentObject`
	// in `machines/manager.svelte.ts`). This means a `find()` on the live
	// buffer can flip null → non-null → null between ticks while the piece is
	// still very much alive, which would cause the detail page to flash the
	// "no longer in buffer" fallback and drop the crop gallery every time.
	//
	// To fix the flicker we cache the last known piece for this UUID in state.
	// It survives transient null lookups and only gets cleared when the UUID
	// itself changes (the user navigates to a different piece).
	type TrackedPieceDetailData = KnownObjectData & { track_detail?: TrackDetail | null };

	let _stickyPiece = $state<TrackedPieceDetailData | null>(null);

	// Fallback hydration for pieces that have already aged out of the WS
	// `recentObjects` ring. We fetch from the backend's persistent-lookup
	// endpoint (`/api/known-objects/<uuid>`) exactly once per route UUID,
	// and `piece` prefers the live ring if the WS ever re-surfaces it (the
	// live payload keeps updating; the fetched snapshot is frozen).
	let _fetchedPiece = $state<TrackedPieceDetailData | null>(null);
	let _fetchStatus = $state<'idle' | 'loading' | 'ok' | 'not_found' | 'error'>('idle');

	$effect(() => {
		// Reset whenever the route UUID changes. Reading `uuid` registers the
		// dependency; the body clears the sticky cache so a different route
		// doesn't briefly show the previous piece's crops.
		void uuid;
		_stickyPiece = null;
		_fetchedPiece = null;
		_fetchStatus = 'idle';
	});

	$effect(() => {
		const list = ctx.machine?.recentObjects ?? [];
		const found = list.find((o) => o.uuid === uuid) ?? null;
		if (found !== null) _stickyPiece = found;
	});

	// Kick off the persistent-lookup fetch when the piece isn't in the live
	// buffer. We avoid refetching by gating on `_fetchStatus === 'idle'` —
	// the UUID-change effect resets it back to 'idle'.
	$effect(() => {
		if (_stickyPiece !== null) return;
		if (_fetchStatus !== 'idle') return;
		const targetUuid = uuid;
		_fetchStatus = 'loading';
		void fetch(`${effectiveBase()}/api/tracked/pieces/${encodeURIComponent(targetUuid)}`)
			.then(async (res) => {
				// Ignore stale responses — the user may have navigated away.
				if (targetUuid !== uuid) return;
				if (res.status === 404) {
					_fetchStatus = 'not_found';
					return;
				}
				if (!res.ok) {
					_fetchStatus = 'error';
					return;
				}
				_fetchedPiece = (await res.json()) as TrackedPieceDetailData;
				_fetchStatus = 'ok';
			})
			.catch(() => {
				if (targetUuid !== uuid) return;
				_fetchStatus = 'error';
			});
	});

	let piece = $derived<TrackedPieceDetailData | null>(_stickyPiece ?? _fetchedPiece);

	let bricklink = $state<BricklinkPartResponse | null>(null);

	let showRawJson = $state(false);
	let zoomImage = $state<{ src: string; label: string } | null>(null);

	// Refetch Bricklink only when the part_id actually changes — otherwise every
	// WS event (updated_at tick etc.) would reset `bricklink` to null and
	// re-fetch, which flickers the "Name" row. If Bricklink returns !ok we
	// quietly leave `bricklink` null — the name falls back to Brickognize's
	// own `part_name` or an em-dash.
	let _lastFetchedPartId: string | null = null;
	$effect(() => {
		const pid = piece?.part_id ?? null;
		if (pid === _lastFetchedPartId) return;
		_lastFetchedPartId = pid;
		bricklink = null;
		if (!pid) return;
		void fetch(`/bricklink/part/${pid}`)
			.then(async (res) => {
				if (res.ok) bricklink = (await res.json()) as BricklinkPartResponse;
			})
			.catch(() => {});
	});

	// Tick so relative timestamps refresh.
	let now_tick = $state(0);
	let timerId: ReturnType<typeof setInterval> | null = null;
	onMount(() => {
		timerId = setInterval(() => (now_tick += 1), 1000);
	});
	onDestroy(() => {
		if (timerId !== null) clearInterval(timerId);
	});

	function dataImageUrl(payload: string | null | undefined): string | null {
		return payload ? `data:image/jpeg;base64,${payload}` : null;
	}

	// Phase 6: piece-crop JPEGs are served from disk via
	// `GET /api/piece-crops/{uuid}/seg{seq}/{kind}/{idx}.jpg`. The SQLite
	// segment payload stores the disk-relative path
	// `piece_crops/<uuid>/seg<seq>/<kind>_<idx>.jpg` — convert it to the
	// API URL by stripping the leading `piece_crops/` prefix, splitting the
	// `<kind>_<idx>` filename, and prepending the machine base. Returns
	// `null` for anything that doesn't match the expected shape (the caller
	// falls back to the b64 payload).
	function pieceCropUrl(disk_path: string | null | undefined): string | null {
		if (typeof disk_path !== 'string' || disk_path.length === 0) return null;
		const stripped = disk_path.replace(/^piece_crops\//, '');
		// Expect: "<uuid>/seg<seq>/<kind>_<idx>.jpg". Bail on anything else.
		const m = stripped.match(/^([^/]+)\/seg(\d+)\/(wedge|piece|snapshot)_(\d+)\.jpg$/);
		if (!m) return null;
		const [, piece_uuid, seq, kind, idx] = m;
		return `${effectiveBase()}/api/piece-crops/${piece_uuid}/seg${seq}/${kind}/${Number(idx)}.jpg`;
	}

	function snapshotImageSrc(snap: SectorSnapshot, prefer: 'piece' | 'wedge'): string | null {
		// Prefer the disk-backed URL (long-cached), fall back to any b64 the
		// live tracker still has in memory. For the "piece" crop we additionally
		// fall back to the wedge path/b64 because older data may only have the
		// wedge variant.
		if (prefer === 'piece') {
			return (
				pieceCropUrl(snap.piece_jpeg_path) ??
				pieceCropUrl(snap.jpeg_path) ??
				dataImageUrl(snap.piece_jpeg_b64) ??
				dataImageUrl(snap.jpeg_b64)
			);
		}
		return pieceCropUrl(snap.jpeg_path) ?? dataImageUrl(snap.jpeg_b64);
	}

	type CropEntry = { src: string; role: string; ts: number | null; used: boolean };

	// --- Tracker-backed crop fetch ----------------------------------------
	// The "Captured Crops" gallery used to surface just top/bottom/thumbnail.
	// That missed every sector snapshot gathered on the C-channels, which is
	// the vast majority of what the piece actually had photographed. We now
	// fetch the tracker detail and enumerate every sector snapshot — the
	// subset the backend actually shipped to Brickognize is flagged via
	// `piece.recognition_used_crop_ts`.
	type PathPoint = [number, number, number];
	type SectorSnapshot = {
		sector_index?: number;
		captured_ts: number;
		start_angle_deg?: number;
		end_angle_deg?: number;
		bbox_x?: number;
		bbox_y?: number;
		width?: number;
		height?: number;
		// Phase 3+: crops live on disk and are referenced by relative path
		// (e.g. "piece_crops/<uuid>/seg<seq>/wedge_000.jpg"). The legacy
		// b64 payload is still populated for the live-tracker path where the
		// snapshot hasn't been flushed yet.
		jpeg_path?: string | null;
		piece_jpeg_path?: string | null;
		jpeg_b64?: string;
		piece_jpeg_b64?: string;
		r_inner?: number;
		r_outer?: number;
	};
	type Segment = {
		// Live tracker uses `source_role`; DB-backed segments use `role`.
		// Accept either and fall back to `role` in the consumers.
		source_role?: string;
		role?: string;
		handoff_from: string | null;
		first_seen_ts: number;
		last_seen_ts: number;
		duration_s: number;
		hit_count: number;
		path_points: number;
		snapshot_width: number;
		snapshot_height: number;
		snapshot_jpeg_b64?: string;
		snapshot_path?: string | null;
		path: PathPoint[];
		channel_center_x: number | null;
		channel_center_y: number | null;
		channel_radius_inner: number | null;
		channel_radius_outer: number | null;
		sector_count: number;
		sector_snapshots?: SectorSnapshot[];
	};
	type BurstFrame = {
		role: string;
		captured_ts: number;
		jpeg_b64: string;
	};
	type TrackDetail = {
		global_id: number;
		created_at?: number;
		finished_at?: number;
		duration_s?: number;
		roles?: string[];
		handoff_count?: number;
		segment_count?: number;
		total_hit_count?: number;
		segments: Segment[];
		live?: boolean;
		burst_frames?: BurstFrame[];
	};

	let trackDetail = $state<TrackDetail | null>(null);
	let _loadedGlobalId: number | null = null;
	let trackPollTimer: ReturnType<typeof setInterval> | null = null;

	// Signature of the fetched track: "live|seg0_snaps,seg1_snaps,..." — used
	// to gate `trackDetail` reassignment so polls that return identical data
	// don't trigger a re-render of the crops `$effect` or the composite SVG.
	function trackSignature(d: TrackDetail | null): string {
		if (!d) return '';
		const counts = d.segments.map((s) => s.sector_snapshots?.length ?? 0).join(',');
		const burstCount = d.burst_frames?.length ?? 0;
		return `${d.live ? 1 : 0}|${counts}|b${burstCount}`;
	}
	let _trackSig = '';

	async function loadTrack(gid: number | null | undefined): Promise<void> {
		if (gid == null || !Number.isFinite(gid)) {
			trackDetail = null;
			_trackSig = '';
			return;
		}
		try {
			const res = await fetch(`${effectiveBase()}/api/feeder/tracking/history/${gid}`);
			if (!res.ok) return;
			const next = (await res.json()) as TrackDetail;
			const nextSig = trackSignature(next);
			if (nextSig !== _trackSig) {
				_trackSig = nextSig;
				trackDetail = next;
			}
		} catch {
			// Silent — the page still renders without the tracker-crop gallery.
		}
	}

	// Phase 6 (unified dossier): the piece detail response already embeds
	// `track_detail` — segments from the DB plus a `live` flag. We prefer
	// that as the source of truth and only hit /api/feeder/tracking/history
	// when the piece is still actively tracked (live === true), where the
	// live manager may have more current sector snapshots / burst frames
	// than what has been flushed to the DB yet.
	$effect(() => {
		const gid = piece?.tracked_global_id ?? null;
		if (gid === _loadedGlobalId) return;
		_loadedGlobalId = gid;
		// Don't wipe `trackDetail` here — the embedded `piece.track_detail`
		// effect below will seed it from the DB-backed response. Live merge
		// happens on top.
	});

	// Primary: seed `trackDetail` from the embedded piece response.
	$effect(() => {
		const embedded = piece?.track_detail ?? null;
		if (!embedded) return;
		const nextSig = trackSignature(embedded);
		if (nextSig !== _trackSig) {
			_trackSig = nextSig;
			trackDetail = embedded;
		}
	});

	// Secondary: when the embedded detail says the piece is still live on
	// the tracker, fetch the fresher live manager detail. The DB-backed
	// segments are a snapshot and miss burst frames / sectors added after
	// the last segment flush.
	$effect(() => {
		if (!piece?.track_detail?.live) return;
		const gid = piece?.tracked_global_id;
		if (gid == null || !Number.isFinite(gid)) return;
		void loadTrack(gid);
	});

	onMount(() => {
		// While the piece is still live on the tracker, sector snapshots
		// keep arriving. Only poll in that case — the DB-backed detail for
		// a finished piece is immutable and doesn't need refreshing.
		trackPollTimer = setInterval(() => {
			if (trackDetail?.live && piece?.tracked_global_id != null) {
				void loadTrack(piece.tracked_global_id);
			}
		}, 1500);
	});

	onDestroy(() => {
		if (trackPollTimer !== null) clearInterval(trackPollTimer);
	});

	const TS_TOLERANCE_S = 0.005;

	function tsWasUsed(captured_ts: number, usedList: number[]): boolean {
		for (const t of usedList) {
			if (Math.abs(t - captured_ts) <= TS_TOLERANCE_S) return true;
		}
		return false;
	}

	// --- Flicker control --------------------------------------------------
	// `piece` is re-assigned on every WS event from the machine, which used to
	// force the `crops` $derived to rebuild and the `{#each}` (keyed by idx)
	// to re-mount every <img>. We now compute crops into a content-keyed cache
	// and only publish a new array when the identifying signature actually
	// changes. We also stabilize the `recognition_used_crop_ts` array reference
	// passed to the composite so it doesn't see a fresh `[]` every tick.
	//
	// A crop's identity is (ts | src) + used flag. Top/bottom snapshots have
	// no captured_ts, so we fall back to the full src string for keying.
	function cropKey(c: CropEntry): string {
		return `${c.ts ?? c.src}`;
	}

	let _cachedCrops = $state<CropEntry[]>([]);
	let _cachedCropsSig = '';

	let _cachedUsedTs = $state<number[]>([]);
	let _cachedUsedTsSig = '';

	$effect(() => {
		const nextUsed: number[] = piece?.recognition_used_crop_ts ?? [];
		const sig = nextUsed.length === 0 ? '' : nextUsed.slice().sort().join(',');
		if (sig !== _cachedUsedTsSig) {
			_cachedUsedTsSig = sig;
			_cachedUsedTs = nextUsed.slice();
		}
	});

	$effect(() => {
		if (!piece) {
			if (_cachedCropsSig !== '') {
				_cachedCropsSig = '';
				_cachedCrops = [];
			}
			return;
		}
		const entries: CropEntry[] = [];
		const usedList = _cachedUsedTs;

		if (trackDetail) {
			for (const seg of trackDetail.segments ?? []) {
				for (const snap of seg.sector_snapshots ?? []) {
					const src = snapshotImageSrc(snap, 'piece');
					if (!src) continue;
					entries.push({
						src,
						role: seg.source_role ?? seg.role ?? 'unknown',
						ts: snap.captured_ts ?? null,
						used: snap.captured_ts != null ? tsWasUsed(snap.captured_ts, usedList) : false
					});
				}
			}
		}

		// Keep the classification chamber top/bottom snapshots as a fallback;
		// they aren't in the tracker history (they come from the snapping
		// station, not the polar tracker).
		const top = dataImageUrl(piece.top_image);
		const bottom = dataImageUrl(piece.bottom_image);
		if (top) {
			entries.push({
				src: top,
				role: 'classification_top',
				ts: piece.carousel_snapping_completed_at ?? piece.classified_at ?? null,
				used: false
			});
		}
		if (bottom) {
			entries.push({
				src: bottom,
				role: 'classification_bottom',
				ts: piece.carousel_snapping_completed_at ?? piece.classified_at ?? null,
				used: false
			});
		}

		if (entries.length === 0) {
			const thumb = dataImageUrl(piece.thumbnail);
			if (thumb) {
				entries.push({
					src: thumb,
					role: 'classification_preview',
					ts: piece.carousel_detected_confirmed_at ?? piece.classified_at ?? piece.updated_at ?? null,
					used: false
				});
			}
		}

		// Sort by timestamp so the gallery reads chronologically.
		entries.sort((a, b) => (a.ts ?? 0) - (b.ts ?? 0));

		// Signature includes key + used flag so the gallery re-renders only
		// when a new crop arrives or its "used" state flips. Note we omit `src`
		// on tracker crops (identified by ts) — the b64 payload for a given
		// captured_ts never changes mid-track and hashing it would defeat the
		// stabilization.
		const sig = entries
			.map((c) => `${cropKey(c)}|${c.used ? 1 : 0}`)
			.join(';');
		if (sig !== _cachedCropsSig) {
			_cachedCropsSig = sig;
			_cachedCrops = entries;
		}
	});

	const crops = $derived(_cachedCrops);
	const usedCropTs = $derived(_cachedUsedTs);
	const usedCropCount = $derived(crops.reduce((n, c) => n + (c.used ? 1 : 0), 0));

	// --- Drop-zone burst --------------------------------------------------
	// Pre+post-event frames from C3 + carousel captured when the piece fell
	// into the classification chamber. Rendered as a filmstrip + enlarged
	// preview. Chronologically pre-sorted on the backend.
	const burstFrames = $derived<BurstFrame[]>(trackDetail?.burst_frames ?? []);
	let selectedBurstIdx = $state(0);
	// Reset the selection whenever the underlying global_id changes so we
	// don't index past the end of a different piece's burst.
	$effect(() => {
		void _loadedGlobalId;
		selectedBurstIdx = 0;
	});
	// Clamp if the frame list shrank (shouldn't happen — entries only grow —
	// but defensive).
	$effect(() => {
		if (selectedBurstIdx >= burstFrames.length) {
			selectedBurstIdx = Math.max(0, burstFrames.length - 1);
		}
	});
	const selectedBurstFrame = $derived<BurstFrame | null>(
		burstFrames[selectedBurstIdx] ?? null
	);
	const burstDurationLabel = $derived.by<string>(() => {
		if (burstFrames.length < 2) return '';
		const first = burstFrames[0].captured_ts;
		const last = burstFrames[burstFrames.length - 1].captured_ts;
		const span = Math.max(0, last - first);
		if (span < 1) return `${(span * 1000).toFixed(0)}ms`;
		return `${span.toFixed(2)}s`;
	});

	function burstRoleClass(role: string): string {
		return role === 'carousel' ? 'text-primary' : 'text-text-muted';
	}

	function burstRoleLabel(role: string): string {
		if (role === 'carousel') return 'C4';
		if (role === 'c_channel_3') return 'C3';
		return role.toUpperCase();
	}

	function formatAbsTs(ts: number | null | undefined): string {
		if (!ts) return '—';
		try {
			const d = new Date(ts * 1000);
			return d.toLocaleTimeString(undefined, { hour12: false }) + '.' +
				String(d.getMilliseconds()).padStart(3, '0');
		} catch {
			return String(ts);
		}
	}

	function formatRelSec(ts: number | null | undefined, anchor: number | null | undefined): string {
		if (!ts || !anchor) return '';
		const d = ts - anchor;
		if (Math.abs(d) < 1) return `+${(d * 1000).toFixed(0)}ms`;
		return `+${d.toFixed(2)}s`;
	}

	function formatRelativeTime(ts: number | null | undefined): string {
		void now_tick;
		if (!ts) return '';
		const diff = Math.max(0, Date.now() / 1000 - ts);
		if (diff < 60) return `${Math.round(diff)}s ago`;
		if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
		return `${Math.round(diff / 3600)}h ago`;
	}

	function formatBin(bin: [unknown, unknown, unknown] | null | undefined): string {
		if (!bin) return '—';
		return `L${bin[0]} · S${bin[1]} · B${bin[2]}`;
	}

	function formatRole(role: string): string {
		if (role === 'classification_preview') return 'C4 preview';
		if (role === 'classification_top') return 'Classification Top';
		if (role === 'classification_bottom') return 'Classification Bottom';
		if (role === 'carousel') return 'Classification Channel';
		if (role === 'c_channel_2') return 'C-Channel 2';
		if (role === 'c_channel_3') return 'C-Channel 3';
		return role;
	}

	function confidenceClass(conf: number | null | undefined): string {
		if (conf == null) return 'text-text-muted';
		const pct = conf * 100;
		if (pct >= 90) return 'text-success';
		if (pct >= 80) return 'text-warning';
		if (pct >= 60) return 'text-warning/70';
		return 'text-danger';
	}

	function formatSyncPercent(ratio: number | null | undefined): string {
		if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return '—';
		return `${(ratio * 100).toFixed(0)}%`;
	}

	function motionSyncClass(ratio: number | null | undefined): string {
		if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return 'text-text-muted';
		if (ratio < 0.5) return 'text-danger';
		if (ratio < 0.85 || ratio > 1.15) return 'text-warning-dark';
		return 'text-success';
	}

	const motionSamples = $derived<CarouselMotionSampleData[]>(piece?.carousel_motion_samples ?? []);
	const recentMotionSamples = $derived<CarouselMotionSampleData[]>(motionSamples.slice(-8).reverse());

	// Timeline: piece lifecycle events with absolute timestamps. We only show
	// events that actually happened.
	type TimelineEvent = { label: string; ts: number };
	const timeline = $derived.by<TimelineEvent[]>(() => {
		if (!piece) return [];
		const events: TimelineEvent[] = [];
		const push = (label: string, ts: number | null | undefined) => {
			if (typeof ts === 'number' && ts > 0) events.push({ label, ts });
		};
		push('Created / first seen', piece.created_at);
		push('Feeding started', piece.feeding_started_at);
		push('First carousel sighting', piece.first_carousel_seen_ts);
		push('Carousel confirmed', piece.carousel_detected_confirmed_at);
		push('Carousel rotate started', piece.carousel_rotate_started_at);
		push('Carousel rotated', piece.carousel_rotated_at);
		push('Snapping started', piece.carousel_snapping_started_at);
		push('Snapping completed', piece.carousel_snapping_completed_at);
		push('Classified', piece.classified_at);
		push('Distributing', piece.distributing_at);
		push('Target bin selected', piece.distribution_target_selected_at);
		push('Distribution motion', piece.distribution_motion_started_at);
		push('Positioned over bin', piece.distribution_positioned_at);
		push('Distributed', piece.distributed_at);
		// Monotonic sort (floats); preserve original ordering when equal.
		events.sort((a, b) => a.ts - b.ts);
		return events;
	});

	const cat_name = $derived(
		piece?.category_id ? sortingProfileStore.getCategoryName(piece.category_id) : null
	);

	const is_unknown = $derived(
		piece?.classification_status === 'unknown' ||
			piece?.classification_status === 'not_found'
	);
	const is_multi_drop = $derived(piece?.classification_status === 'multi_drop_fail');

	function statusLabel(obj: KnownObjectData): string {
		if (obj.stage === 'distributed') return 'Distributed';
		if (obj.stage === 'distributing') return 'Distributing';
		const s = obj.classification_status;
		if (s === 'classifying') return 'Classifying';
		if (s === 'classified') return 'Classified';
		if (s === 'unknown') return 'Unknown';
		if (s === 'not_found') return 'Not recognized';
		if (s === 'multi_drop_fail') return 'Multi-drop fail';
		return 'Pending';
	}

	function statusChipClass(obj: KnownObjectData): string {
		if (obj.classification_status === 'multi_drop_fail') return 'border-danger text-danger';
		if (obj.classification_status === 'unknown' || obj.classification_status === 'not_found') {
			return 'border-warning text-warning-dark';
		}
		if (obj.stage === 'distributed') return 'border-text-muted text-text-muted';
		if (obj.stage === 'distributing') return 'border-primary text-primary';
		if (obj.classification_status === 'classified') return 'border-success text-success';
		return 'border-border text-text-muted';
	}
</script>

<svelte:head>
	<title>Piece {uuid.slice(0, 8)} · Sorter</title>
</svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="flex flex-col gap-4 p-4 sm:p-6">
		<header class="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
			<div class="flex flex-wrap items-center gap-3">
				<a
					href="/tracked"
					class="inline-flex items-center gap-1.5 border border-border bg-surface px-2.5 py-1.5 text-sm text-text-muted hover:text-text"
				>
					<ArrowLeft size={14} />
					Back
				</a>
				<span class="font-mono text-lg font-semibold text-text">
					{uuid.slice(0, 8)}
				</span>
				{#if piece}
					<span class={`inline-flex items-center border px-2 py-0.5 text-xs font-semibold uppercase tracking-wider ${statusChipClass(piece)}`}>
						{statusLabel(piece)}
					</span>
					{#if is_multi_drop}
						<span class="inline-flex items-center border border-danger bg-danger/10 px-2 py-0.5 text-xs font-semibold uppercase tracking-wider text-danger">
							Multi-drop
						</span>
					{/if}
				{/if}
			</div>
			{#if piece?.tracked_global_id != null}
				<a
					href={`/tracked/${piece.tracked_global_id}`}
					class="inline-flex items-center gap-1.5 border border-border bg-surface px-2.5 py-1.5 text-sm text-text-muted hover:text-text"
					title="Open tracker-level record (all angular crops)"
				>
					<ExternalLink size={14} />
					Track #{piece.tracked_global_id}
				</a>
			{/if}
		</header>

		{#if !piece}
			{#if _fetchStatus === 'loading' || _fetchStatus === 'idle'}
				<div class="border border-border bg-surface p-4 text-sm text-text-muted">
					Loading piece detail…
				</div>
			{:else if _fetchStatus === 'not_found'}
				<div class="border border-border bg-surface p-4 text-sm text-text-muted">
					This piece is not in our records. Go back to the
					<a href="/tracked" class="text-primary underline">tracker list</a>
					to pick another.
				</div>
			{:else}
				<div class="border border-border bg-surface p-4 text-sm text-text-muted">
					Could not load this piece — check backend connection.
				</div>
			{/if}
		{:else}
			<!-- Identity & classification summary -->
			<section class="grid grid-cols-1 gap-3 lg:grid-cols-2">
				<div class="flex flex-col border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
						Classification
					</div>
					<div class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 px-3 py-3 text-sm">
						<span class="text-text-muted">Part ID</span>
						<span class="font-mono text-text">{piece.part_id ?? '—'}</span>

						<span class="text-text-muted">Name</span>
						<span class="text-text">
							{#if piece.part_name}
								{piece.part_name}
							{:else if bricklink?.name}
								{bricklink.name}
							{:else}
								—
							{/if}
						</span>

						<span class="text-text-muted">Color</span>
						<span class="text-text">
							{piece.color_name && piece.color_name !== 'Any Color' ? piece.color_name : '—'}
						</span>

						<span class="text-text-muted">Category</span>
						<span class="text-text">{cat_name ?? '—'}</span>

						<span class="text-text-muted">Confidence</span>
						<span class={`font-semibold tabular-nums ${confidenceClass(piece.confidence)}`}>
							{typeof piece.confidence === 'number'
								? `${(piece.confidence * 100).toFixed(0)}%`
								: '—'}
						</span>

						<span class="text-text-muted">Source view</span>
						<span class="text-text">{piece.brickognize_source_view ?? '—'}</span>
					</div>
				</div>

				<div class="flex flex-col border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
						Routing
					</div>
					<div class="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 px-3 py-3 text-sm">
						<span class="text-text-muted">Stage</span>
						<span class="text-text">{piece.stage}</span>

						<span class="text-text-muted">Destination bin</span>
						<span class="font-mono tabular-nums text-text">
							{#if piece.destination_bin}
								{formatBin(piece.destination_bin)}
							{:else if is_unknown || is_multi_drop}
								<span class="text-text-muted">discard bin</span>
							{:else}
								—
							{/if}
						</span>

						<span class="text-text-muted">Tracker</span>
						<span class="font-mono tabular-nums text-text">
							{piece.tracked_global_id ?? '—'}
						</span>

						<span class="text-text-muted">Last update</span>
						<span class="text-text">
							{formatAbsTs(piece.updated_at)}
							<span class="ml-1 text-text-muted">({formatRelativeTime(piece.updated_at)})</span>
						</span>
					</div>
				</div>
			</section>

			<section class="flex flex-col border border-border bg-surface">
				<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
					Carousel motion
				</div>
				<div class="grid gap-3 px-3 py-3 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
					<div class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
						<div class="flex flex-col">
							<span class="text-text-muted">Current sync</span>
							<span class={`font-semibold tabular-nums ${motionSyncClass(piece.carousel_motion_sync_ratio)}`}>
								{formatSyncPercent(piece.carousel_motion_sync_ratio)}
							</span>
						</div>
						<div class="flex flex-col">
							<span class="text-text-muted">Average sync</span>
							<span class={`font-semibold tabular-nums ${motionSyncClass(piece.carousel_motion_sync_ratio_avg)}`}>
								{formatSyncPercent(piece.carousel_motion_sync_ratio_avg)}
							</span>
						</div>
						<div class="flex flex-col">
							<span class="text-text-muted">Samples</span>
							<span class="tabular-nums text-text">{piece.carousel_motion_sample_count ?? 0}</span>
						</div>
						<div class="flex flex-col">
							<span class="text-text-muted">Range</span>
							<span class="tabular-nums text-text">
								{#if piece.carousel_motion_sync_ratio_min != null && piece.carousel_motion_sync_ratio_max != null}
									{formatSyncPercent(piece.carousel_motion_sync_ratio_min)} to {formatSyncPercent(piece.carousel_motion_sync_ratio_max)}
								{:else}
									—
								{/if}
							</span>
						</div>
						<div class="flex flex-col">
							<span class="text-text-muted">Piece speed</span>
							<span class="tabular-nums text-text">
								{typeof piece.carousel_motion_piece_speed_deg_per_s === 'number'
									? `${piece.carousel_motion_piece_speed_deg_per_s.toFixed(1)} deg/s`
									: '—'}
							</span>
						</div>
						<div class="flex flex-col">
							<span class="text-text-muted">Platter speed</span>
							<span class="tabular-nums text-text">
								{typeof piece.carousel_motion_platter_speed_deg_per_s === 'number'
									? `${piece.carousel_motion_platter_speed_deg_per_s.toFixed(1)} deg/s`
									: '—'}
							</span>
						</div>
						<div class="flex flex-col">
							<span class="text-text-muted">Slow samples</span>
							<span class="tabular-nums text-text">{piece.carousel_motion_under_sync_sample_count ?? 0}</span>
						</div>
						<div class="flex flex-col">
							<span class="text-text-muted">Fast samples</span>
							<span class="tabular-nums text-text">{piece.carousel_motion_over_sync_sample_count ?? 0}</span>
						</div>
						<div class="flex flex-col">
							<span class="text-text-muted">First sighting</span>
							<span class="tabular-nums text-text">
								{typeof piece.first_carousel_seen_angle_deg === 'number'
									? `${piece.first_carousel_seen_angle_deg.toFixed(1)}°`
									: '—'}
							</span>
						</div>
					</div>

					<div class="border border-border/70 bg-bg/40 p-3">
						<div class="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
							Recent sync samples
						</div>
						{#if recentMotionSamples.length === 0}
							<div class="text-sm text-text-muted">
								No motion samples captured yet for this piece.
							</div>
						{:else}
							<div class="grid gap-2 sm:grid-cols-2">
								{#each recentMotionSamples as sample (`${sample.observed_at}-${sample.sync_ratio}`)}
									<div class="border border-border bg-surface px-2.5 py-2 text-sm">
										<div class="flex items-center justify-between gap-2">
											<span class={`font-semibold tabular-nums ${motionSyncClass(sample.sync_ratio)}`}>
												{formatSyncPercent(sample.sync_ratio)}
											</span>
											<span class="tabular-nums text-xs text-text-muted">
												{formatRelSec(sample.observed_at, piece.first_carousel_seen_ts ?? piece.created_at)}
											</span>
										</div>
										<div class="mt-1 flex items-center justify-between gap-2 text-xs text-text-muted">
											<span>{sample.piece_speed_deg_per_s.toFixed(1)} deg/s piece</span>
											<span>{sample.carousel_speed_deg_per_s.toFixed(1)} deg/s platter</span>
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			</section>

			<!-- Arrival snapshot: full carousel frame at the instant the piece
			     first appeared on C4 (dropping in from C3), side-by-side with
			     the Brickognize reference so the operator can eyeball whether
			     the classification was right. -->
			{#if piece.drop_snapshot || piece.brickognize_preview_url || bricklink?.thumbnail_url}
				{@const ref_drop_src = bricklink?.thumbnail_url
					? `https:${bricklink.thumbnail_url}`
					: (piece.brickognize_preview_url ?? null)}
				<section class="border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
						Arrival snapshot
					</div>
					<div class="flex flex-wrap gap-3 p-3">
						{#if piece.drop_snapshot}
							{@const drop_src = dataImageUrl(piece.drop_snapshot) as string}
							<button
								type="button"
								class="flex flex-col border border-border bg-bg text-left hover:border-primary/70"
								onclick={() => (zoomImage = { src: drop_src, label: 'At arrival' })}
							>
								<div class="relative flex h-64 w-64 items-center justify-center bg-white">
									<img src={drop_src} alt="arrival snapshot" class="h-full w-full object-contain" loading="lazy" />
								</div>
								<div class="px-2 py-1.5 text-sm text-text-muted">At arrival</div>
							</button>
						{:else}
							<div class="flex h-64 w-64 items-center justify-center border border-border bg-bg text-sm text-text-muted">
								No snapshot captured
							</div>
						{/if}
						{#if ref_drop_src}
							<button
								type="button"
								class="flex flex-col border border-border bg-bg text-left hover:border-primary/70"
								onclick={() => (zoomImage = { src: ref_drop_src, label: 'Brickognize says' })}
							>
								<div class="relative flex h-64 w-64 items-center justify-center bg-white">
									<img src={ref_drop_src} alt="brickognize reference" class="h-full w-full object-contain" loading="lazy" />
								</div>
								<div class="flex items-center justify-between gap-2 px-2 py-1.5 text-sm text-text-muted">
									<span>Brickognize says</span>
									<span class="tabular-nums">{piece.part_id ?? ''}</span>
								</div>
							</button>
						{/if}
					</div>
				</section>
			{/if}

			<!-- Image gallery + Brickognize reference -->
			<section class="border border-border bg-surface">
				<div class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm">
					<div class="font-medium text-text">
						Captured crops
						<span class="ml-2 text-text-muted">{crops.length}</span>
					</div>
					{#if usedCropCount > 0}
						<div class="flex items-center gap-2 text-text-muted">
							<span class="inline-block h-3 w-3 border-2 border-primary"></span>
							<span>{usedCropCount} shipped to Brickognize</span>
						</div>
					{/if}
				</div>
				<div class="p-3">
					{#if crops.length === 0}
						<div class="text-sm text-text-muted">No crops available for this piece.</div>
					{:else}
						<div class="grid gap-2" style="grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));">
							{#each crops as crop (cropKey(crop))}
								<button
									type="button"
									class={`flex flex-col bg-bg text-left hover:border-primary/70 ${
										crop.used ? 'border-2 border-primary' : 'border border-border'
									}`}
									title={crop.used ? 'Shipped to Brickognize for classification' : formatRole(crop.role)}
									onclick={() => (zoomImage = { src: crop.src, label: formatRole(crop.role) })}
								>
									<div class="relative aspect-square w-full bg-white">
										<img src={crop.src} alt={crop.role} class="h-full w-full object-contain" loading="lazy" />
									</div>
									<div class="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-text-muted">
										<span>{formatRole(crop.role)}</span>
										<span class="tabular-nums">{formatAbsTs(crop.ts)}</span>
									</div>
								</button>
							{/each}
							{#if piece.brickognize_preview_url || bricklink?.thumbnail_url}
								{@const ref_src = bricklink?.thumbnail_url
									? `https:${bricklink.thumbnail_url}`
									: (piece.brickognize_preview_url as string)}
								<button
									type="button"
									class="flex flex-col border border-border bg-bg text-left hover:border-primary/70"
									onclick={() => (zoomImage = { src: ref_src, label: 'Brickognize reference' })}
								>
									<div class="relative aspect-square w-full bg-white">
										<img src={ref_src} alt="reference" class="h-full w-full object-contain" loading="lazy" />
									</div>
									<div class="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-text-muted">
										<span>Brickognize ref.</span>
										<span class="tabular-nums">{piece.part_id ?? ''}</span>
									</div>
								</button>
							{/if}
						</div>
					{/if}
				</div>
			</section>

			<!-- Drop burst: fashion-shoot sequence from the C3→C4 fall -->
			{#if burstFrames.length > 0}
				<section class="border border-border bg-surface">
					<div class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm">
						<span class="font-medium text-text">Drop Burst</span>
						<span class="text-text-muted">
							<span class="tabular-nums">{burstFrames.length}</span>
							<span class="mx-1">frames</span>
							{#if burstDurationLabel}
								<span class="mx-1">·</span>
								<span class="tabular-nums">{burstDurationLabel}</span>
							{/if}
						</span>
					</div>
					{#if selectedBurstFrame}
						<div class="flex flex-col items-center gap-1 border-b border-border bg-bg p-3">
							<img
								src={`data:image/jpeg;base64,${selectedBurstFrame.jpeg_b64}`}
								alt="burst frame {selectedBurstIdx + 1} of {burstFrames.length}"
								class="max-h-[480px] max-w-full object-contain"
								loading="lazy"
							/>
							<div class="flex items-center gap-2 text-sm text-text-muted">
								<span class={`font-semibold uppercase tracking-wider ${burstRoleClass(selectedBurstFrame.role)}`}>
									{burstRoleLabel(selectedBurstFrame.role)}
								</span>
								<span class="tabular-nums">{formatAbsTs(selectedBurstFrame.captured_ts)}</span>
								<span class="text-text-muted">· frame {selectedBurstIdx + 1} / {burstFrames.length}</span>
							</div>
						</div>
					{/if}
					<div class="flex flex-row gap-1 overflow-x-auto px-3 py-2">
						{#each burstFrames as frame, idx (frame.captured_ts + '|' + idx)}
							<button
								type="button"
								class={`flex h-32 flex-col flex-shrink-0 bg-bg text-left hover:border-primary/70 ${
									idx === selectedBurstIdx ? 'border-2 border-primary' : 'border border-border'
								}`}
								onclick={() => (selectedBurstIdx = idx)}
								title={`${burstRoleLabel(frame.role)} · ${formatAbsTs(frame.captured_ts)}`}
							>
								<img
									src={`data:image/jpeg;base64,${frame.jpeg_b64}`}
									alt="burst frame {idx + 1}"
									class="h-full w-auto flex-shrink-0 object-contain"
									loading="lazy"
								/>
							</button>
						{/each}
					</div>
				</section>
			{/if}

			<!-- Track path (pie-chart composite) -->
			{#if piece.tracked_global_id != null}
				<section class="border border-border bg-surface">
					<div class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm">
						<span class="font-medium text-text">Track path</span>
						<a
							href={`/tracked/${piece.tracked_global_id}`}
							class="inline-flex items-center gap-1.5 text-text-muted hover:text-text"
							title="Open the full tracker record"
						>
							<ExternalLink size={14} />
							Track #{piece.tracked_global_id}
						</a>
					</div>
					<div class="p-3">
						<TrackPathComposite
							globalId={piece.tracked_global_id}
							usedCropTs={usedCropTs}
							detailSnapshot={trackDetail}
						/>
					</div>
				</section>
			{/if}

			<!-- Lifecycle timeline -->
			<section class="border border-border bg-surface">
				<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
					Lifecycle timeline
				</div>
				<div class="p-3">
					{#if timeline.length === 0}
						<div class="text-sm text-text-muted">No lifecycle events recorded yet.</div>
					{:else}
						{@const anchor = timeline[0].ts}
						<ol class="flex flex-col">
							{#each timeline as ev, idx (idx)}
								<li class="relative flex items-baseline gap-3 border-l border-border pl-4">
									<span class="absolute -left-[5px] top-1.5 h-2 w-2 bg-primary"></span>
									<span class="min-w-[12rem] text-sm text-text">{ev.label}</span>
									<span class="font-mono text-sm tabular-nums text-text-muted">
										{formatAbsTs(ev.ts)}
									</span>
									{#if idx > 0}
										<span class="font-mono text-xs tabular-nums text-text-muted">
											{formatRelSec(ev.ts, anchor)}
										</span>
									{/if}
									<span class="flex-1"></span>
								</li>
							{/each}
						</ol>
					{/if}
				</div>
			</section>

			<!-- Brickognize response / part reference -->
			{#if bricklink}
				<section class="border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
						Brickognize match
					</div>
					<div class="flex flex-wrap items-start gap-3 p-3">
						{#if bricklink.thumbnail_url}
							<img
								src={`https:${bricklink.thumbnail_url}`}
								alt={bricklink.name ?? piece.part_id ?? ''}
								class="h-20 w-20 flex-shrink-0 border border-border bg-white object-contain"
								loading="lazy"
							/>
						{/if}
						<div class="flex min-w-0 flex-1 flex-col gap-1 text-sm">
							<div class="font-mono text-base font-semibold text-text">
								{piece.part_id ?? '—'}
							</div>
							<div class="text-text">{piece.part_name ?? bricklink.name ?? '—'}</div>
							{#if bricklink.type}
								<div class="text-text-muted">{bricklink.type}</div>
							{/if}
							{#if typeof piece.confidence === 'number'}
								<div class={`tabular-nums ${confidenceClass(piece.confidence)}`}>
									Confidence {(piece.confidence * 100).toFixed(0)}%
								</div>
							{/if}
						</div>
					</div>
				</section>
			{/if}

			<!-- Raw JSON toggle -->
			<section class="border border-border bg-surface">
				<button
					type="button"
					class="flex w-full items-center gap-2 border-b border-border bg-bg px-3 py-2 text-sm text-text-muted hover:text-text"
					onclick={() => (showRawJson = !showRawJson)}
				>
					{#if showRawJson}
						<ChevronDown size={14} />
					{:else}
						<ChevronRight size={14} />
					{/if}
					<span>View raw JSON</span>
				</button>
				{#if showRawJson}
					<pre class="max-h-96 overflow-auto bg-bg p-3 text-xs text-text-muted">{JSON.stringify(
							piece,
							null,
							2
						)}</pre>
				{/if}
			</section>
		{/if}
	</div>
</div>

{#if zoomImage}
	<button
		type="button"
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
		onclick={() => (zoomImage = null)}
		aria-label="Close enlarged image"
	>
		<div class="flex max-h-full max-w-full flex-col gap-2 border border-border bg-bg p-3">
			<img
				src={zoomImage.src}
				alt={zoomImage.label}
				class="max-h-[80vh] max-w-[80vw] object-contain"
			/>
			<div class="text-sm text-text-muted">{zoomImage.label}</div>
		</div>
	</button>
{/if}
