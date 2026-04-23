<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ArrowLeft, Camera, ExternalLink, Hash, Image as ImageIcon, Route } from 'lucide-svelte';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import TrackPathComposite from '$lib/components/TrackPathComposite.svelte';
	import { capturedCropUrl, dataImageUrl, pieceCropUrl } from '$lib/recent-pieces';
	import { formatTrackLabel } from '$lib/trackLabel';
	import { getMachineContext } from '$lib/machines/context';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { KnownObjectData } from '$lib/api/events';
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

	// Fetch the DB-backed detail once per route UUID. We run this even when
	// the live WS ring already has the piece, because `track_detail`
	// (segments + sector snapshots) is only on the fetched payload — the
	// sticky piece only carries the KnownObjectData surface.
	$effect(() => {
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

	// Live WS updates win for the piece fields that tick every frame (stage,
	// classification_status, ...), but `track_detail` only lives on the
	// DB-backed fetch response — merge it in so the composite doesn't see
	// `null` while the piece is still in the live ring.
	let piece = $derived<TrackedPieceDetailData | null>(
		_stickyPiece
			? {
					..._stickyPiece,
					track_detail: _stickyPiece.track_detail ?? _fetchedPiece?.track_detail ?? null
				}
			: _fetchedPiece
	);

	let bricklink = $state<BricklinkPartResponse | null>(null);

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

	function snapshotImageSrc(snap: SectorSnapshot, prefer: 'piece' | 'wedge'): string | null {
		// Prefer the disk-backed URL (long-cached), fall back to any b64 the
		// live tracker still has in memory. For the "piece" crop we additionally
		// fall back to the wedge path/b64 because older data may only have the
		// wedge variant.
		const base = effectiveBase();
		if (prefer === 'piece') {
			return (
				pieceCropUrl(snap.piece_jpeg_path, base) ??
				pieceCropUrl(snap.jpeg_path, base) ??
				dataImageUrl(snap.piece_jpeg_b64) ??
				dataImageUrl(snap.jpeg_b64)
			);
		}
		return pieceCropUrl(snap.jpeg_path, base) ?? dataImageUrl(snap.jpeg_b64);
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
		relative_ms?: number;
		jpeg_b64?: string;
		jpeg_path?: string | null;
		piece_jpeg_path?: string | null;
		crop_jpeg_path?: string | null;
		width?: number;
		height?: number;
	};
	type MatrixShot = {
		name?: string;
		status?: string;
		triggered_at?: number;
		pre_window_s?: number;
		post_window_s?: number;
		frame_count?: number;
		frames?: BurstFrame[];
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
		matrix_shot?: MatrixShot;
	};

	let trackDetail = $state<TrackDetail | null>(null);

	// Signature of the embedded track detail: "live|seg0_snaps,seg1_snaps,..."
	// — gates `trackDetail` reassignment so identical payloads don't trigger
	// re-renders of the crops `$effect` or the composite SVG.
	function trackSignature(d: TrackDetail | null): string {
		if (!d) return '';
		const counts = d.segments.map((s) => s.sector_snapshots?.length ?? 0).join(',');
		const burstCount = d.matrix_shot?.frames?.length ?? d.burst_frames?.length ?? 0;
		return `${d.live ? 1 : 0}|${counts}|b${burstCount}`;
	}
	let _trackSig = '';

	// rt/ publishes every piece_registered/classified/distributed event
	// straight into the DB-backed dossier, so `piece.track_detail` embedded
	// in the `/api/tracked/pieces/{uuid}` response is the single source of
	// truth — no separate live-tracker fetch needed.
	$effect(() => {
		const embedded = piece?.track_detail ?? null;
		if (!embedded) return;
		const nextSig = trackSignature(embedded);
		if (nextSig !== _trackSig) {
			_trackSig = nextSig;
			trackDetail = embedded;
		}
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
			const thumb = capturedCropUrl(piece, effectiveBase());
			if (thumb) {
				entries.push({
					src: thumb,
					role: 'classification_preview',
					ts:
						piece.carousel_detected_confirmed_at ?? piece.classified_at ?? piece.updated_at ?? null,
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
		const sig = entries.map((c) => `${cropKey(c)}|${c.used ? 1 : 0}`).join(';');
		if (sig !== _cachedCropsSig) {
			_cachedCropsSig = sig;
			_cachedCrops = entries;
		}
	});

	const crops = $derived(_cachedCrops);
	const usedCropTs = $derived(_cachedUsedTs);
	const usedCropCount = $derived(crops.reduce((n, c) => n + (c.used ? 1 : 0), 0));

	// --- Matrix-shot ------------------------------------------------------
	// Reverse-buffered C4 frames captured at first C4 registration.
	// Older payloads used `burst_frames`; keep them as a compatibility source.
	const matrixShot = $derived<MatrixShot | null>(trackDetail?.matrix_shot ?? null);
	const burstFrames = $derived<BurstFrame[]>(matrixShot?.frames ?? trackDetail?.burst_frames ?? []);
	let selectedBurstIdx = $state(0);
	// Reset the selection whenever the underlying global_id changes so we
	// don't index past the end of a different piece's burst.
	$effect(() => {
		void piece?.tracked_global_id;
		selectedBurstIdx = 0;
	});
	// Clamp if the frame list shrank (shouldn't happen — entries only grow —
	// but defensive).
	$effect(() => {
		if (selectedBurstIdx >= burstFrames.length) {
			selectedBurstIdx = Math.max(0, burstFrames.length - 1);
		}
	});
	const selectedBurstFrame = $derived<BurstFrame | null>(burstFrames[selectedBurstIdx] ?? null);
	const burstDurationLabel = $derived.by<string>(() => {
		if (burstFrames.length < 2) return '';
		const first = burstFrames[0].captured_ts;
		const last = burstFrames[burstFrames.length - 1].captured_ts;
		const span = Math.max(0, last - first);
		if (span < 1) return `${(span * 1000).toFixed(0)}ms`;
		return `${span.toFixed(2)}s`;
	});

	function burstRoleLabel(role: string): string {
		if (role === 'carousel') return 'C4';
		if (role === 'c_channel_3') return 'C3';
		return role.toUpperCase();
	}

	function burstFrameSrc(frame: BurstFrame | null): string | null {
		if (!frame) return null;
		return pieceCropUrl(frame.jpeg_path, effectiveBase()) ?? dataImageUrl(frame.jpeg_b64);
	}

	function burstFrameCropSrc(frame: BurstFrame | null): string | null {
		if (!frame) return null;
		return (
			pieceCropUrl(frame.piece_jpeg_path, effectiveBase()) ??
			pieceCropUrl(frame.crop_jpeg_path, effectiveBase())
		);
	}

	function burstFrameDisplaySrc(frame: BurstFrame | null): string | null {
		return burstFrameCropSrc(frame) ?? burstFrameSrc(frame);
	}

	function formatAbsTs(ts: number | null | undefined): string {
		if (!ts) return '—';
		try {
			const d = new Date(ts * 1000);
			return (
				d.toLocaleTimeString(undefined, { hour12: false }) +
				'.' +
				String(d.getMilliseconds()).padStart(3, '0')
			);
		} catch {
			return String(ts);
		}
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

	const cat_name = $derived(
		piece?.category_id ? sortingProfileStore.getCategoryName(piece.category_id) : null
	);
	const category_label = $derived(cat_name ?? piece?.part_category ?? piece?.category_id ?? null);
	const bin_label = $derived(
		piece?.destination_bin ? formatBin(piece.destination_bin) : (piece?.bin_id ?? null)
	);

	const is_unknown = $derived(
		piece?.classification_status === 'unknown' || piece?.classification_status === 'not_found'
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
		if (obj.classification_status === 'multi_drop_fail')
			return 'border-danger bg-danger/10 text-danger';
		if (obj.classification_status === 'unknown' || obj.classification_status === 'not_found') {
			return 'border-warning bg-warning/10 text-warning-dark';
		}
		if (obj.stage === 'distributed') return 'border-text-muted bg-text-muted/10 text-text-muted';
		if (obj.stage === 'distributing') return 'border-primary bg-primary/10 text-primary';
		if (obj.classification_status === 'classified')
			return 'border-success bg-success/10 text-success';
		return 'border-border bg-bg text-text-muted';
	}

	const primaryTitle = $derived.by<string>(() => {
		if (!piece) return `Piece ${uuid.slice(0, 8)}`;
		if (piece.part_name) return piece.part_name;
		if (bricklink?.name) return bricklink.name;
		if (piece.part_id) return piece.part_id;
		if (piece.classification_status === 'pending') return 'Unclassified C4 piece';
		return 'Tracked piece';
	});

	const latestCrop = $derived<CropEntry | null>(crops[crops.length - 1] ?? null);
	const latestCropSrc = $derived.by<string | null>(() => {
		if (latestCrop?.src) return latestCrop.src;
		return piece ? capturedCropUrl(piece, effectiveBase()) : null;
	});

	const recognizerImageSrc = $derived.by<string | null>(() => {
		if (bricklink?.thumbnail_url) return `https:${bricklink.thumbnail_url}`;
		return piece?.brickognize_preview_url ?? null;
	});
</script>

<svelte:head>
	<title>Piece {uuid.slice(0, 8)} · Sorter</title>
</svelte:head>

<div class="detail-shell min-h-screen bg-bg">
	<AppHeader />
	<div class="mx-auto flex w-full max-w-[1800px] flex-col gap-4 p-4 sm:p-6">
		{#if !piece}
			{#if _fetchStatus === 'loading' || _fetchStatus === 'idle'}
				<div class="detail-section border border-border bg-surface p-4 text-sm text-text-muted">
					Loading piece detail…
				</div>
			{:else if _fetchStatus === 'not_found'}
				<div class="detail-section border border-border bg-surface p-4 text-sm text-text-muted">
					This piece is not in our records. Go back to the
					<a href="/tracked" class="text-primary underline">tracker list</a>
					to pick another.
				</div>
			{:else}
				<div class="detail-section border border-border bg-surface p-4 text-sm text-text-muted">
					Could not load this piece — check backend connection.
				</div>
			{/if}
		{:else}
			<header class="detail-hero border border-border bg-surface">
				<div class="flex flex-wrap items-center gap-3 px-3 py-2">
					<a
						href="/tracked"
						class="inline-flex min-h-10 items-center gap-2 border border-border bg-bg px-3 text-sm font-medium text-text-muted transition-[transform,border-color,background-color,color] hover:border-primary/60 hover:text-text active:scale-[0.96]"
					>
						<ArrowLeft size={15} />
						Back
					</a>
					<div class="min-w-0 flex-1">
						<div class="flex flex-wrap items-center gap-2">
							<h1 class="detail-title truncate text-xl font-semibold tracking-[-0.03em] text-text">
								{primaryTitle}
							</h1>
							<span
								class={`inline-flex items-center border px-2 py-0.5 text-xs font-semibold tracking-wider uppercase ${statusChipClass(piece)}`}
							>
								{statusLabel(piece)}
							</span>
						</div>
						<div class="mt-1 flex flex-wrap gap-2 text-xs text-text-muted">
							<span class="inline-flex items-center gap-1.5 font-mono tabular-nums">
								<Hash size={12} />
								{uuid.slice(0, 12)}
							</span>
							<span class="inline-flex items-center gap-1.5">
								<Route size={12} />
								{piece.stage}
							</span>
							{#if typeof piece.confidence === 'number'}
								<span class={`font-mono tabular-nums ${confidenceClass(piece.confidence)}`}>
									{(piece.confidence * 100).toFixed(0)}%
								</span>
							{/if}
						</div>
					</div>
					{#if piece.tracked_global_id != null}
						<a
							href={`/tracked/${piece.tracked_global_id}`}
							class="inline-flex min-h-10 items-center gap-2 border border-border bg-bg px-3 text-sm text-text-muted transition-[transform,border-color,background-color,color] hover:border-primary/60 hover:text-text active:scale-[0.96]"
							title="Open tracker-level record (all angular crops)"
						>
							<ExternalLink size={15} />
							Track #{formatTrackLabel(piece.tracked_global_id) ?? piece.tracked_global_id}
						</a>
					{/if}
				</div>
			</header>

			<section class="grid gap-3 lg:grid-cols-[minmax(340px,0.85fr)_minmax(0,1.15fr)]">
				<div class="detail-section overflow-hidden border border-border bg-surface">
					<div class="flex items-center gap-2 border-b border-border bg-bg px-3 py-2">
						<ImageIcon size={16} class="text-primary" />
						<h2 class="text-sm font-semibold text-text">Prime Visual</h2>
					</div>
					<div class="grid grid-cols-2 gap-2 p-2">
						<div class="overflow-hidden border border-border bg-bg">
							<div class="border-b border-border px-2 py-1 text-xs font-medium text-text-muted">
								Latest crop
							</div>
							{#if latestCropSrc}
								<button
									type="button"
									class="group flex h-48 w-full items-center justify-center bg-white p-1 transition-[transform] active:scale-[0.96]"
									onclick={() =>
										(zoomImage = {
											src: latestCropSrc,
											label: latestCrop ? formatRole(latestCrop.role) : 'Latest crop'
										})}
								>
									<img
										src={latestCropSrc}
										alt="latest crop"
										class="image-outline h-full w-full object-contain transition-transform duration-200 group-hover:scale-[1.02]"
										loading="lazy"
									/>
								</button>
							{:else}
								<div class="flex h-48 items-center justify-center text-sm text-text-muted">
									No crop
								</div>
							{/if}
						</div>
						<div class="overflow-hidden border border-border bg-bg">
							<div class="border-b border-border px-2 py-1 text-xs font-medium text-text-muted">
								Recognized image
							</div>
							{#if recognizerImageSrc}
								<button
									type="button"
									class="group flex h-48 w-full items-center justify-center bg-white p-1 transition-[transform] active:scale-[0.96]"
									onclick={() =>
										(zoomImage = { src: recognizerImageSrc, label: 'Recognized image' })}
								>
									<img
										src={recognizerImageSrc}
										alt="recognizer reference"
										class="image-outline h-full w-full object-contain transition-transform duration-200 group-hover:scale-[1.02]"
										loading="lazy"
									/>
								</button>
							{:else}
								<div class="flex h-48 items-center justify-center text-sm text-text-muted">
									No reference
								</div>
							{/if}
						</div>
					</div>
				</div>

				<div class="detail-section flex flex-col border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-semibold text-text">
						Recognize
					</div>
					<div class="grid gap-x-4 gap-y-2 px-3 py-3 text-sm sm:grid-cols-2">
						<div class="compact-row">
							<span>Part</span>
							<strong class="font-mono text-text">{piece.part_id ?? '—'}</strong>
						</div>
						<div class="compact-row">
							<span>Confidence</span>
							<strong class={`font-mono tabular-nums ${confidenceClass(piece.confidence)}`}>
								{typeof piece.confidence === 'number'
									? `${(piece.confidence * 100).toFixed(0)}%`
									: '—'}
							</strong>
						</div>
						<div class="compact-row sm:col-span-2">
							<span>Name</span>
							<strong class="text-right text-text">
								{piece.part_name ?? bricklink?.name ?? '—'}
							</strong>
						</div>
						<div class="compact-row">
							<span>Color</span>
							<strong class="text-text">
								{piece.color_name && piece.color_name !== 'Any Color' ? piece.color_name : '—'}
							</strong>
						</div>
						<div class="compact-row">
							<span>Category</span>
							<strong class="text-right text-text">{category_label ?? '—'}</strong>
						</div>
						<div class="compact-row sm:col-span-2">
							<span>Source view</span>
							<strong class="text-right text-text">{piece.brickognize_source_view ?? '—'}</strong>
						</div>
					</div>
				</div>
			</section>

			<section class="grid gap-3 md:grid-cols-[minmax(0,1.05fr)_minmax(320px,0.95fr)]">
				<!-- Matrix-shot: reverse-buffered C4 fall sequence -->
				<div class="detail-section overflow-hidden border border-border bg-surface">
					<div
						class="flex items-center justify-between gap-3 border-b border-border bg-bg px-3 py-2"
					>
						<div class="flex items-center gap-2">
							<Camera size={16} class="text-primary" />
							<h2 class="text-sm font-semibold text-text">Matrix-Shot</h2>
							<span class="font-mono text-xs text-text-muted tabular-nums">
								{burstFrames.length}{#if burstDurationLabel}
									· {burstDurationLabel}{/if}
							</span>
						</div>
						{#if selectedBurstFrame && !burstFrameCropSrc(selectedBurstFrame)}
							<span
								class="border border-warning/40 bg-warning/10 px-2 py-0.5 text-xs text-warning-dark"
							>
								full frame
							</span>
						{/if}
					</div>
					{#if burstFrames.length === 0}
						<div
							class="flex min-h-56 items-center justify-center bg-bg/50 p-6 text-sm text-text-muted"
						>
							No Matrix-Shot frames captured.
						</div>
					{:else if selectedBurstFrame}
						{@const selectedBurstSrc = burstFrameDisplaySrc(selectedBurstFrame)}
						<div class="matrix-stage-bg flex min-h-[280px] items-center justify-center p-2">
							{#if selectedBurstSrc}
								<button
									type="button"
									class="group flex w-full items-center justify-center transition-[transform] active:scale-[0.96]"
									onclick={() =>
										(zoomImage = {
											src: selectedBurstSrc,
											label: `Matrix-Shot frame ${selectedBurstIdx + 1}`
										})}
								>
									<img
										src={selectedBurstSrc}
										alt="matrix-shot frame {selectedBurstIdx + 1} of {burstFrames.length}"
										class="image-outline max-h-[330px] max-w-full object-contain transition-transform duration-200 group-hover:scale-[1.005]"
										loading="lazy"
									/>
								</button>
							{/if}
						</div>
						<div
							class="flex items-center justify-between border-t border-border px-3 py-1.5 text-xs"
						>
							<span class="font-mono text-text-muted tabular-nums">
								{formatAbsTs(selectedBurstFrame.captured_ts)} · {selectedBurstIdx +
									1}/{burstFrames.length}
							</span>
							<span class="text-text-muted">
								{#if burstFrameCropSrc(selectedBurstFrame)}
									cropped piece
								{:else}
									crop pending
								{/if}
							</span>
						</div>
						<div
							class="filmstrip flex gap-1.5 overflow-x-auto border-t border-border bg-surface px-2 py-2"
						>
							{#each burstFrames as frame, idx (frame.captured_ts + '|' + idx)}
								{@const frameSrc = burstFrameDisplaySrc(frame)}
								<button
									type="button"
									class={`group flex h-16 w-24 flex-shrink-0 items-center justify-center bg-bg transition-[transform,border-color,background-color] hover:border-primary/70 active:scale-[0.96] ${
										idx === selectedBurstIdx ? 'border-2 border-primary' : 'border border-border'
									}`}
									onclick={() => (selectedBurstIdx = idx)}
									title={`${burstRoleLabel(frame.role)} · ${formatAbsTs(frame.captured_ts)}`}
								>
									{#if frameSrc}
										<img
											src={frameSrc}
											alt="matrix-shot frame {idx + 1}"
											class="image-outline h-full w-full object-cover transition-transform duration-200 group-hover:scale-[1.02]"
											loading="lazy"
										/>
									{/if}
								</button>
							{/each}
						</div>
					{/if}
				</div>

				{#if piece.tracked_global_id != null}
					<div class="detail-section overflow-hidden border border-border bg-surface">
						<div
							class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm"
						>
							<span class="font-semibold text-text">Track path</span>
							<a
								href={`/tracked/${piece.tracked_global_id}`}
								class="inline-flex items-center gap-1.5 text-text-muted hover:text-text"
								title="Open the full tracker record"
							>
								<ExternalLink size={14} />
								#{formatTrackLabel(piece.tracked_global_id) ?? piece.tracked_global_id}
							</a>
						</div>
						<div class="track-path-compact max-h-[430px] overflow-auto p-2">
							<TrackPathComposite {usedCropTs} detailSnapshot={trackDetail} />
						</div>
					</div>
				{/if}
			</section>

			<section class="detail-section overflow-hidden border border-border bg-surface">
				<div
					class="flex flex-wrap items-center justify-between gap-3 border-b border-border bg-bg px-3 py-2 text-sm"
				>
					<div class="flex items-center gap-2 font-semibold text-text">
						<ImageIcon size={16} class="text-primary" />
						Captured crops
						<span class="font-mono text-text-muted tabular-nums">{crops.length}</span>
					</div>
					{#if usedCropCount > 0}
						<div class="flex items-center gap-2 text-xs text-text-muted">
							<span class="inline-block h-3 w-3 border-2 border-primary"></span>
							<span>{usedCropCount} used</span>
						</div>
					{/if}
				</div>
				<div class="crop-strip flex gap-2 overflow-x-auto p-2">
					{#if crops.length === 0}
						<div
							class="flex h-44 min-w-full items-center justify-center border border-dashed border-border bg-bg text-sm text-text-muted"
						>
							No crops available.
						</div>
					{:else}
						{#each crops as crop (cropKey(crop))}
							<button
								type="button"
								class={`group flex w-36 flex-shrink-0 flex-col overflow-hidden bg-bg text-left transition-[transform,border-color,background-color] hover:border-primary/70 active:scale-[0.96] ${
									crop.used ? 'border-2 border-primary' : 'border border-border'
								}`}
								title={crop.used
									? 'Shipped to Brickognize for classification'
									: formatRole(crop.role)}
								onclick={() => (zoomImage = { src: crop.src, label: formatRole(crop.role) })}
							>
								<div class="relative flex h-36 w-full items-center justify-center bg-white p-1">
									<img
										src={crop.src}
										alt={crop.role}
										class="image-outline h-full w-full object-contain transition-transform duration-200 group-hover:scale-[1.02]"
										loading="lazy"
									/>
								</div>
								<div class="grid gap-0.5 border-t border-border px-2 py-1.5 text-[11px]">
									<span class="truncate font-medium text-text">{formatRole(crop.role)}</span>
									<span class="font-mono text-text-muted tabular-nums">{formatAbsTs(crop.ts)}</span>
								</div>
							</button>
						{/each}
					{/if}
				</div>
			</section>

			<section class="grid gap-3 md:grid-cols-[minmax(0,0.8fr)_minmax(320px,0.8fr)]">
				<div class="detail-section flex flex-col border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-semibold text-text">
						Routing
					</div>
					<div class="grid gap-y-2 px-3 py-3 text-sm">
						<div class="compact-row">
							<span>Stage</span>
							<strong class="text-text">{piece.stage}</strong>
						</div>
						<div class="compact-row">
							<span>Bin</span>
							<strong class="font-mono text-text tabular-nums">
								{#if bin_label}
									{bin_label}
								{:else if is_unknown || is_multi_drop}
									discard
								{:else}
									—
								{/if}
							</strong>
						</div>
						<div class="compact-row">
							<span>Tracker</span>
							<strong class="font-mono text-text tabular-nums">
								{formatTrackLabel(piece.tracked_global_id) ?? '—'}
							</strong>
						</div>
					</div>
				</div>

				<section
					class="detail-section flex flex-col border border-border bg-surface md:col-span-2 xl:col-span-1"
				>
					<div
						class="flex items-center justify-between gap-2 border-b border-border bg-bg px-3 py-2"
					>
						<h2 class="text-sm font-semibold text-text">Motion</h2>
						<span
							class={`border px-2 py-0.5 text-xs font-semibold tabular-nums ${motionSyncClass(piece.carousel_motion_sync_ratio)}`}
						>
							{formatSyncPercent(piece.carousel_motion_sync_ratio)}
						</span>
					</div>
					<div class="grid grid-cols-3 gap-2 px-3 py-3 text-xs">
						<div>
							<span class="block text-text-muted">Avg</span>
							<span
								class={`font-mono tabular-nums ${motionSyncClass(piece.carousel_motion_sync_ratio_avg)}`}
							>
								{formatSyncPercent(piece.carousel_motion_sync_ratio_avg)}
							</span>
						</div>
						<div>
							<span class="block text-text-muted">Samples</span>
							<span class="font-mono text-text tabular-nums">
								{piece.carousel_motion_sample_count ?? 0}
							</span>
						</div>
						<div>
							<span class="block text-text-muted">Angle</span>
							<span class="font-mono text-text tabular-nums">
								{typeof piece.first_carousel_seen_angle_deg === 'number'
									? `${piece.first_carousel_seen_angle_deg.toFixed(1)}°`
									: '—'}
							</span>
						</div>
					</div>
				</section>
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
				class="image-outline max-h-[80vh] max-w-[80vw] object-contain"
			/>
			<div class="text-sm text-text-muted">{zoomImage.label}</div>
		</div>
	</button>
{/if}

<style>
	:global(html) {
		-webkit-font-smoothing: antialiased;
	}

	.detail-hero,
	.detail-section {
		box-shadow:
			0 18px 50px -42px rgba(20, 20, 18, 0.45),
			0 1px 0 rgba(255, 255, 255, 0.72) inset;
	}

	.detail-title {
		text-wrap: balance;
	}

	.compact-row {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 1rem;
		border-bottom: 1px solid color-mix(in srgb, var(--color-border, #d8d5ce) 65%, transparent);
		padding-bottom: 0.5rem;
	}

	.compact-row > span {
		color: var(--color-text-muted, #6d6961);
	}

	.compact-row > strong {
		font-weight: 600;
	}

	.matrix-stage-bg {
		background:
			radial-gradient(
				circle at 50% 35%,
				rgba(255, 255, 255, 0.92),
				rgba(250, 249, 246, 0.65) 42%,
				rgba(232, 229, 221, 0.72) 100%
			),
			linear-gradient(135deg, rgba(255, 255, 255, 0.7), rgba(230, 227, 219, 0.7));
	}

	.image-outline {
		box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.1);
	}

	:global(.dark) .image-outline {
		box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.1);
	}

	.filmstrip {
		scrollbar-width: thin;
		scrollbar-color: color-mix(in srgb, var(--color-primary, #2f9cb3) 55%, transparent) transparent;
	}

	.crop-strip {
		scrollbar-width: thin;
		scrollbar-color: color-mix(in srgb, var(--color-primary, #2f9cb3) 45%, transparent) transparent;
	}

	.track-path-compact :global(.flex.flex-col.gap-3) {
		gap: 0.5rem;
	}

	.track-path-compact :global(svg) {
		max-height: 360px;
	}
</style>
