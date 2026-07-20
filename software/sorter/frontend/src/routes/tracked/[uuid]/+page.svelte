<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/state';
	import { ArrowLeft, ChevronDown, ChevronRight, ExternalLink } from 'lucide-svelte';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import TrackPathComposite from '$lib/components/TrackPathComposite.svelte';
	import ImageInfoBadge from '$lib/components/ImageInfoBadge.svelte';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import PieceInfoCard from '$lib/components/pieces/PieceInfoCard.svelte';
	import PieceThumbGrid from '$lib/components/pieces/PieceThumbGrid.svelte';
	import type { InfoRow, Thumb } from '$lib/components/pieces/types';
	import {
		diskToDisplay,
		fetchDiskImages,
		fetchDiskLinkImages,
		type DisplayImage
	} from '$lib/components/records/piece-images';
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { KnownObjectData, ClassificationAttempt } from '$lib/api/events';
	import type { components } from '$lib/api/rest';
	import { pieceStore, type PieceDetailEnvelope, type PieceSummary } from '$lib/pieces';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';

	type BricklinkPartResponse = components['schemas']['BricklinkPartResponse'];

	const ctx = getMachineContext();
	onMount(() => {
		void sortingProfileStore.load();
	});

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? getBackendHttpBase();
	}

	let uuid = $derived(String(page.params.uuid));

	// Piece lookup — sticky by UUID.
	//
	// The shared piece store is fed from WS events. Entries update on every
	// piece event and live (ws-origin) payloads can be demoted/evicted, so a
	// `find()` on the store can flip null → non-null → null between ticks while
	// the piece is still very much alive, which would cause the detail page to
	// flash the fallback and drop the crop gallery every time.
	//
	// To fix the flicker we cache the last known piece for this UUID in state.
	// It survives transient null lookups and only gets cleared when the UUID
	// itself changes (the user navigates to a different piece).
	let _stickyPiece = $state<KnownObjectData | null>(null);

	// Fallback hydration for pieces that are no longer live: the tiered detail
	// endpoint (`/api/pieces/<uuid>`) is fetched exactly once per route UUID.
	// A memory hit carries the full KnownObject payload; a disk hit degrades to
	// the durable summary + on-disk images ('summary_only').
	let _fetchedPiece = $state<KnownObjectData | null>(null);
	let _fetchStatus = $state<'idle' | 'loading' | 'ok' | 'summary_only' | 'not_found' | 'error'>(
		'idle'
	);
	let _diskSummary = $state<PieceSummary | null>(null);
	let _diskImages = $state<DisplayImage[]>([]);

	$effect(() => {
		const entries = pieceStore.entriesFor(ctx.machine?.identity?.machine_id ?? null);
		const found = entries.find((p) => p.uuid === uuid)?.ws ?? null;
		if (found !== null) _stickyPiece = found;
	});

	// Kick off one detail fetch per UUID even if the piece is still live in
	// the store. The live payload intentionally stays lightweight; this fetch
	// carries the heavier detail-only fields for this route.
	$effect(() => {
		if (_fetchStatus !== 'idle') return;
		const targetUuid = uuid;
		_fetchStatus = 'loading';
		void fetch(`${effectiveBase()}/api/pieces/${encodeURIComponent(targetUuid)}`)
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
				const env = (await res.json()) as PieceDetailEnvelope;
				if (targetUuid !== uuid) return;
				if (env.detail_available && env.detail) {
					_fetchedPiece = env.detail;
					_fetchStatus = 'ok';
					return;
				}
				_diskSummary = env.summary ?? { uuid: targetUuid };
				_fetchStatus = 'summary_only';
				const base = effectiveBase();
				const disk = await fetchDiskImages(base, targetUuid).catch(() => []);
				const linkDisk = await fetchDiskLinkImages(base, targetUuid).catch(() => []);
				if (targetUuid !== uuid) return;
				// Ground truth + the link model's guesses, merged for display only
				// (they live in separate stores).
				_diskImages = [...disk.map((d) => diskToDisplay(base, targetUuid, d)), ...linkDisk];
			})
			.catch(() => {
				if (targetUuid !== uuid) return;
				_fetchStatus = 'error';
			});
	});

	let piece = $derived(_stickyPiece ?? _fetchedPiece);

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

	type CropEntry = {
		src: string;
		role: string;
		ts: number | null;
		used: boolean;
		seq?: number;
		total?: number;
		score?: number | null;
		channel?: number | null;
		sharpness?: number | null;
	};

	// Channel the image came from, for the corner badge. Never guess: an image
	// whose channel wasn't recorded is shown as unknown rather than silently
	// claiming C4, which is how every upstream crop ended up labelled as a
	// classification-chamber burst frame.
	function channelLabel(channel: number | null | undefined): string {
		if (channel === 2 || channel === 3 || channel === 4) return `C${channel}`;
		return '—';
	}

	// Human label for an image's origin, derived from what was actually
	// recorded on it.
	function sourceLabel(source: string | null | undefined, channel?: number | null): string {
		if (source === 'c4_burst') return 'C4 burst';
		if (source === 'link_match') {
			return channel === 2 || channel === 3 ? `Link match · C${channel}` : 'Link match';
		}
		if (source === 'upstream') {
			return channel === 2 || channel === 3 ? `Upstream · C${channel}` : 'Upstream';
		}
		return source || 'unknown';
	}

	// --- Tracker-backed crop fetch ----------------------------------------
	// The "Captured Crops" gallery used to surface just top/bottom/thumbnail.
	// That missed every sector snapshot gathered on the C-channels, which is
	// the vast majority of what the piece actually had photographed. We now
	// fetch the tracker detail and enumerate every sector snapshot — the
	// subset the backend actually shipped to Brickognize is flagged via
	// `piece.recognition_used_crop_ts`.
	type PathPoint = [number, number, number];
	type SectorSnapshot = {
		captured_ts: number;
		start_angle_deg?: number;
		end_angle_deg?: number;
		jpeg_b64: string;
		piece_jpeg_b64?: string;
	};
	type Segment = {
		source_role: string;
		sector_snapshots?: SectorSnapshot[];
	};
	type BurstFrame = {
		role: string;
		captured_ts: number;
		jpeg_b64: string;
	};
	type TrackDetail = {
		global_id: number;
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

	// Only refetch when the *global id* actually changes. `piece` is reassigned
	// on every WS event so a naive dependency would clear+refetch the track on
	// every tick, re-rendering the whole crops gallery and composite.
	$effect(() => {
		const gid = piece?.tracked_global_id ?? null;
		if (gid === _loadedGlobalId) return;
		_loadedGlobalId = gid;
		trackDetail = null;
		_trackSig = '';
		void loadTrack(gid);
	});

	onMount(() => {
		// While the piece is still live on the tracker, sector snapshots keep
		// arriving. Poll at the same cadence the track page uses.
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
		return `${c.role}|${c.ts ?? 'no-ts'}|${c.src}`;
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
					const src = dataImageUrl(snap.piece_jpeg_b64 ?? snap.jpeg_b64);
					if (!src) continue;
					entries.push({
						src,
						role: seg.source_role,
						ts: snap.captured_ts ?? null,
						used: snap.captured_ts != null ? tsWasUsed(snap.captured_ts, usedList) : false
					});
				}
			}
		}

		// Two DELIBERATELY separate lists on the piece:
		//   recognition_image_set — ground truth, the C4 burst; `used` =
		//     shipped to Brickognize in the applied request. This list feeds
		//     piece_images -> Hive -> training data.
		//   link_match_image_set  — the piece-link model's GUESSES from C2/C3.
		//     Separate field, separate storage, never synced as piece images,
		//     so they can never poison the ground truth. `used` marks guesses
		//     that were fused into the applied request.
		const recogSet = _fetchedPiece?.recognition_image_set ?? [];
		const burstTotal = recogSet.length;
		let recogSeq = 0;
		for (const entry of recogSet) {
			const src = dataImageUrl(entry.image);
			if (!src) continue;
			recogSeq += 1;
			entries.push({
				src,
				role: 'recognition_capture',
				ts: entry.ts ?? null,
				used: entry.used ?? false,
				seq: recogSeq,
				total: burstTotal,
				channel: entry.channel ?? 4,
				sharpness: entry.sharpness ?? null
			});
		}
		const linkSet = _fetchedPiece?.link_match_image_set ?? [];
		let linkSeq = 0;
		for (const entry of linkSet) {
			const src = dataImageUrl(entry.image);
			if (!src) continue;
			linkSeq += 1;
			entries.push({
				src,
				role: 'link_match',
				ts: entry.ts ?? null,
				used: entry.used ?? false,
				seq: linkSeq,
				total: linkSet.length,
				score: entry.score ?? null,
				channel: entry.channel ?? null,
				sharpness: entry.sharpness ?? null
			});
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
	// Latest C4 burst capture time — when the classification chamber snapped its
	// pics.
	const c4SnapTs = $derived.by<number | null>(() => {
		let ref: number | null = null;
		for (const c of crops) {
			if (c.role === 'recognition_capture' && typeof c.ts === 'number') {
				ref = ref === null ? c.ts : Math.max(ref, c.ts);
			}
		}
		return ref;
	});

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
	const selectedBurstFrame = $derived<BurstFrame | null>(burstFrames[selectedBurstIdx] ?? null);
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
			return (
				d.toLocaleTimeString(undefined, { hour12: false }) +
				'.' +
				String(d.getMilliseconds()).padStart(3, '0')
			);
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
		if (role === 'recognition_capture') return 'Recognition Capture';
		if (role === 'link_match') return 'Link Match (C2/C3)';
		if (role === 'classification_top') return 'Classification Top';
		if (role === 'classification_bottom') return 'Classification Bottom';
		if (role === 'carousel') return 'Classification Channel';
		if (role === 'c_channel_2') return 'C-Channel 2';
		if (role === 'c_channel_3') return 'C-Channel 3';
		return role;
	}

	function formatCropLabel(crop: CropEntry): string {
		if (crop.role === 'recognition_capture' && crop.seq && crop.total) {
			return `Burst ${crop.seq}/${crop.total}`;
		}
		if (crop.role === 'link_match' && crop.seq && crop.total) {
			const pct = formatMatchProbability(crop.score);
			return pct ? `Link ${crop.seq}/${crop.total} · ${pct}` : `Link ${crop.seq}/${crop.total}`;
		}
		return formatRole(crop.role);
	}

	// The piece-link model's P(same physical piece). Distinct from `used`: these
	// crops never went to Brickognize, so this is the model's claim, not a
	// record of what produced the classification.
	function formatMatchProbability(score: number | null | undefined): string {
		if (score == null || !Number.isFinite(score)) return '';
		return `${Math.round(score * 100)}% match`;
	}

	// Motion-blur / focus measure (Laplacian variance) of a burst crop; higher =
	// sharper. Shown rounded — the absolute value is camera/lighting dependent, so
	// it's mainly useful for comparing crops of the same piece.
	function formatSharpness(sharpness: number | null | undefined): string {
		if (sharpness == null || !Number.isFinite(sharpness)) return '';
		return `${Math.round(sharpness)}`;
	}

	function cropInfoRows(crop: CropEntry): { label: string; value: string }[] {
		const rows: { label: string; value: string }[] = [
			{ label: 'Type', value: formatRole(crop.role) },
			{
				label: 'Shipped',
				value:
					crop.role === 'link_match'
						? 'No — link matches are not sent to Brickognize'
						: crop.used
							? 'Yes'
							: 'No'
			}
		];
		if (crop.role === 'link_match' && crop.score != null) {
			rows.push({ label: 'Model match', value: formatMatchProbability(crop.score) });
		}
		if (crop.sharpness != null && Number.isFinite(crop.sharpness)) {
			rows.push({ label: 'Sharpness', value: formatSharpness(crop.sharpness) });
		}
		if (crop.ts != null) {
			rows.push({ label: 'Captured', value: formatAbsTs(crop.ts) });
		}
		return rows;
	}

	// The parallel Brickognize requests fired for this piece (combined + the
	// single-image variants). They run concurrently, not as retries; the one
	// flagged applied=True is the highest-confidence call whose result was used.
	const attempts = $derived(piece?.classification_attempts ?? []);
	// Which request rows are expanded to show their sent crops + stock photo.
	let expandedAttempts = $state<Set<number>>(new Set());

	function toggleAttempt(i: number): void {
		const next = new Set(expandedAttempts);
		if (next.has(i)) next.delete(i);
		else next.add(i);
		expandedAttempts = next;
	}

	function attemptName(a: ClassificationAttempt): string {
		if (a.strategy === 'single_burst') return 'Single burst frame';
		if (a.strategy === 'combined') return 'Combined (fused set)';
		return a.label ?? a.strategy;
	}

	function attemptOutcome(a: ClassificationAttempt): string {
		if (a.error) return 'error';
		if (!a.found) return 'no match';
		const pct = a.confidence != null ? ` · ${(a.confidence * 100).toFixed(0)}%` : '';
		return `${a.part_id ?? '?'}${pct}`;
	}

	function attemptInputs(a: ClassificationAttempt): string {
		const parts: string[] = [];
		if (a.n_burst) parts.push(`${a.n_burst} burst`);
		return parts.length ? parts.join(' + ') : 'no images';
	}

	// The crops actually submitted in this request, resolved from the recognition
	// set by matching the attempt's captured-image timestamps against each crop's.
	function attemptImages(a: ClassificationAttempt): CropEntry[] {
		const tss = a.image_ts ?? [];
		if (tss.length === 0) return [];
		return crops.filter((c) => c.ts != null && tsWasUsed(c.ts, tss));
	}

	// Which service actually answered for this piece. Pieces classified before
	// providers were recorded have no value — "—" rather than a guess.
	const PROVIDER_LABELS: Record<string, string> = {
		brickognize: 'Brickognize',
		hive_basically: 'basically color model'
	};

	function providerLabel(id: string | null | undefined): string {
		if (!id) return '—';
		return PROVIDER_LABELS[id] ?? id;
	}

	function confidenceClass(conf: number | null | undefined): string {
		if (conf == null) return 'text-text-muted';
		const pct = conf * 100;
		if (pct >= 90) return 'text-success';
		if (pct >= 80) return 'text-warning';
		if (pct >= 60) return 'text-warning/70';
		return 'text-danger';
	}

	// Local-catalog (BrickLink) price formatter. Sub-cent values keep an extra
	// digit so cheap parts don't collapse to "$0.00"; non-positive/missing → em-dash.
	function fmtPrice(v: unknown): string {
		if (typeof v !== 'number' || !isFinite(v) || v <= 0) return '—';
		return v >= 0.01 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`;
	}

	// The four BrickLink price buckets in display order: sold (last 6 months)
	// first since that's what the routing headline prefers, then current listings.
	const PRICE_BUCKETS: [string, string][] = [
		['ord_used', 'Sold · Used'],
		['ord_new', 'Sold · New'],
		['inv_used', 'Listed · Used'],
		['inv_new', 'Listed · New']
	];

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
		piece?.classification_status === 'unknown' || piece?.classification_status === 'not_found'
	);
	const is_multi_drop = $derived(piece?.classification_status === 'multi_drop_fail');

	function formatSummaryBin(bin: PieceSummary['bin']): string {
		if (!bin) return '—';
		return `L${bin.x} · S${bin.y} · B${bin.z}`;
	}

	// --- Card row builders -------------------------------------------------
	// The live (in-memory) and disk-fallback views describe the same piece from
	// two payload shapes. Both normalize into these row lists and render through
	// PieceInfoCard, so the two views can't drift apart the way they had.
	function classificationRows(o: {
		part_id?: string | null;
		part_name?: string | null;
		color_name?: string | null;
		color_provider?: string | null;
		mold_provider?: string | null;
		category_id?: string | null;
		confidence?: number | null;
		color_confidence?: number | null;
		source_view?: string | null;
	}): InfoRow[] {
		// Mold and color are scored by (potentially) different providers, so each
		// confidence sits directly under the source that produced it. A single
		// "Confidence" row read as covering both, which it never did.
		const rows: InfoRow[] = [
			{ label: 'Part ID', value: o.part_id ?? '—', mono: true },
			{ label: 'Name', value: o.part_name ?? '—' },
			{ label: 'Mold source', value: providerLabel(o.mold_provider) },
			{
				label: 'Mold confidence',
				value: typeof o.confidence === 'number' ? `${(o.confidence * 100).toFixed(0)}%` : '—',
				valueClass: `font-semibold tabular-nums ${confidenceClass(o.confidence)}`
			},
			{
				label: 'Color',
				value: o.color_name && o.color_name !== 'Any Color' ? o.color_name : '—'
			},
			{ label: 'Color source', value: providerLabel(o.color_provider) },
			{
				label: 'Color confidence',
				value:
					typeof o.color_confidence === 'number'
						? `${(o.color_confidence * 100).toFixed(0)}%`
						: '—',
				valueClass: `font-semibold tabular-nums ${confidenceClass(o.color_confidence)}`
			},
			{
				label: 'Category',
				value: o.category_id ? (sortingProfileStore.getCategoryName(o.category_id) ?? '—') : '—'
			}
		];
		if (o.source_view) rows.push({ label: 'Source view', value: o.source_view });
		return rows;
	}

	// One "Record" card for both views — each field appears only when the
	// payload actually carries it, rather than two hand-maintained card bodies.
	function recordRows(o: {
		stage?: string | null;
		bin_label: string;
		est_value?: number | null;
		run_id?: string | null;
		tracked_global_id?: number | null;
		seen_at?: number | null;
		recorded_at?: number | null;
		updated_at?: number | null;
	}): InfoRow[] {
		const rows: InfoRow[] = [];
		if (o.stage) rows.push({ label: 'Stage', value: o.stage });
		rows.push({
			label: 'Destination bin',
			value: o.bin_label,
			valueClass: 'font-mono tabular-nums text-text'
		});
		if (o.est_value != null) {
			rows.push({
				label: 'Est. value',
				value: fmtPrice(o.est_value),
				valueClass: 'tabular-nums text-text'
			});
		}
		if (o.run_id) rows.push({ label: 'Run', value: o.run_id, mono: true });
		if (o.tracked_global_id != null) {
			rows.push({
				label: 'Tracker',
				value: String(o.tracked_global_id),
				valueClass: 'font-mono tabular-nums text-text'
			});
		}
		if (o.seen_at != null) {
			rows.push({ label: 'Seen', value: new Date(o.seen_at * 1000).toLocaleString() });
		}
		if (o.recorded_at != null) {
			rows.push({ label: 'Recorded', value: new Date(o.recorded_at * 1000).toLocaleString() });
		}
		if (o.updated_at != null) {
			rows.push({
				label: 'Last update',
				value: `${formatAbsTs(o.updated_at)} (${formatRelativeTime(o.updated_at)})`
			});
		}
		return rows;
	}

	// Catalog reference shot for the identified part — BrickLink's photo when the
	// local catalog has one, else whatever Brickognize returned. Shown once, in
	// the Classification card, the same way the disk view shows `preview_url`.
	const refImageSrc = $derived<string | null>(
		bricklink?.thumbnail_url
			? `https:${bricklink.thumbnail_url}`
			: (piece?.brickognize_preview_url ?? null)
	);

	// Destination bin reads as the discard bin for pieces that were never
	// identified — they still get routed, just not to a part-specific bin.
	function liveBinLabel(): string {
		if (piece?.destination_bin) return formatBin(piece.destination_bin);
		if (is_unknown || is_multi_drop) return 'discard bin';
		return '—';
	}

	const diskThumbs = $derived<Thumb<DisplayImage>[]>(
		_diskImages.map((img, i) => ({
			key: String(i),
			src: img.src,
			alt: img.source,
			caption: sourceLabel(img.source, img.channel),
			used: img.used,
			ref: img
		}))
	);

	function toThumb(c: CropEntry): Thumb<CropEntry> {
		return {
			key: cropKey(c),
			src: c.src,
			alt: c.role,
			title: c.used ? 'Shipped to Brickognize for classification' : formatCropLabel(c),
			used: c.used,
			caption: formatCropLabel(c),
			captionRight: formatAbsTs(c.ts),
			ref: c
		};
	}

	// The two sources, shown separately: the C4 burst the chamber captured, and
	// the upstream C2/C3 views of the same piece. In both, `used` (a stroke on
	// the tile) means the image was actually shipped to Brickognize in the
	// request whose result was applied.
	const burstThumbs = $derived<Thumb<CropEntry>[]>(
		crops.filter((c) => c.role === 'recognition_capture').map(toThumb)
	);

	// Link matches first, ranked by the model's probability; then any other
	// upstream crop the tracker happened to keep, which carries no score.
	const otherChannelThumbs = $derived<Thumb<CropEntry>[]>(
		crops
			.filter((c) => c.role !== 'recognition_capture')
			.slice()
			.sort((a, b) => {
				const sa = a.role === 'link_match' ? (a.score ?? -1) : -2;
				const sb = b.role === 'link_match' ? (b.score ?? -1) : -2;
				return sb - sa;
			})
			.map(toThumb)
	);
	const linkMatchCount = $derived(crops.filter((c) => c.role === 'link_match').length);

</script>

<svelte:head>
	<title>Piece {uuid.slice(0, 8)} · Sorter</title>
</svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="mx-auto flex w-full max-w-[1600px] flex-col gap-4 p-4 sm:p-6">
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
					{#if piece.stage === 'distributed'}
						<span
							class="inline-flex items-center border border-border bg-surface px-2 py-0.5 text-xs font-semibold tracking-wider text-text-muted uppercase"
						>
							Distributed
						</span>
					{:else if piece.stage === 'distributing'}
						<span
							class="inline-flex items-center border border-primary bg-primary/10 px-2 py-0.5 text-xs font-semibold tracking-wider text-primary uppercase"
						>
							Distributing
						</span>
					{/if}
					<PieceStatusBadge
						status={piece.classification_status}
						requestFailed={Boolean(piece.request_failed)}
						dead={Boolean(piece.dead)}
					/>
				{:else if _diskSummary}
					<PieceStatusBadge
						status={_diskSummary.classification_status}
						dead={Boolean(_diskSummary.dead)}
					/>
				{/if}
			</div>
			<div class="flex flex-wrap items-center gap-3">
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
			</div>
		</header>

		{#if !piece}
			{#if _fetchStatus === 'summary_only' && _diskSummary}
				{@const ds = _diskSummary}
				<section class="grid grid-cols-1 gap-3 lg:grid-cols-2">
					<PieceInfoCard
						title="Classification"
						rows={classificationRows(ds)}
						image={ds.preview_url}
						imageAlt="brickognize reference"
						onImageClick={() =>
							(zoomImage = {
								src: ds.preview_url as string,
								label: ds.part_name ?? ds.part_id ?? 'Brickognize reference'
							})}
					/>
					<PieceInfoCard
						title="Record"
						rows={recordRows({
							bin_label: formatSummaryBin(ds.bin),
							est_value: ds.est_value,
							run_id: ds.run_id,
							seen_at: ds.seen_at,
							recorded_at: ds.recorded_at
						})}
					/>
				</section>

				<div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
					{#if diskThumbs.length > 0}
						<section class="flex flex-col border border-border bg-surface">
							<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
								Stored images
								<span class="ml-2 text-text-muted">{diskThumbs.length}</span>
							</div>
							<div class="p-3">
								<PieceThumbGrid
									items={diskThumbs}
									minPx={120}
									onZoom={(t) => (zoomImage = { src: t.src, label: t.ref.source })}
								/>
							</div>
						</section>
					{/if}
				</div>
			{:else if _fetchStatus === 'loading' || _fetchStatus === 'idle'}
				<div class="border border-border bg-surface p-4 text-sm text-text-muted">
					Loading piece…
				</div>
			{:else if _fetchStatus === 'not_found'}
				<div class="border border-border bg-surface p-4 text-sm text-text-muted">
					No trace of this piece — it isn't in backend memory, the durable piece records, or the
					on-disk image store. Go back to the
					<a href="/tracked" class="text-primary underline">tracker list</a>
					for persistent track records.
				</div>
			{:else}
				<div class="border border-border bg-surface p-4 text-sm text-text-muted">
					Could not load this piece. Check the backend connection and try again.
				</div>
			{/if}
		{:else}
			<!-- Identity & classification summary -->
			<section class="grid grid-cols-1 gap-3 lg:grid-cols-2">
				<PieceInfoCard
					title="Classification"
					rows={classificationRows({
						part_id: piece.part_id,
						part_name: piece.part_name ?? bricklink?.name ?? null,
						color_name: piece.color_name,
						color_provider: piece.color_provider,
						mold_provider: piece.mold_provider,
						category_id: piece.category_id,
						confidence: piece.confidence,
						color_confidence: piece.color_confidence,
						source_view: piece.brickognize_source_view
					})}
					image={refImageSrc}
					imageAlt="brickognize reference"
					onImageClick={() =>
						(zoomImage = {
							src: refImageSrc as string,
							label: piece.part_name ?? piece.part_id ?? 'Brickognize reference'
						})}
				/>
				<PieceInfoCard
					title="Record"
					rows={recordRows({
						stage: piece.stage,
						bin_label: liveBinLabel(),
						tracked_global_id: piece.tracked_global_id,
						updated_at: piece.updated_at
					})}
				/>
			</section>

			<!-- Pricing — every BrickLink bucket from the local parts.db catalog.
			     The headline `moving_avg_price` (what routing uses) is the first
			     non-empty of these, sold·new preferred; the table shows all four
			     so you can see whatever source actually exists for this part. -->
			{#if piece.piece_metadata}
				{@const md = piece.piece_metadata as Record<string, any>}
				{@const price = (md.price ?? null) as Record<string, any> | null}
				{@const bl = (md.bricklink ?? null) as Record<string, any> | null}
				<section class="border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
						Pricing — local catalog{md.price_currency ? ` · BrickLink ${md.price_currency}` : ''}
					</div>
					<div class="flex flex-col gap-3 p-3 text-sm">
						<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
							<span class="text-text-muted">Moving avg (routing)</span>
							<span class="text-base font-semibold text-success tabular-nums">
								{typeof md.moving_avg_price === 'number' ? fmtPrice(md.moving_avg_price) : '—'}
							</span>
							<span class="text-xs text-text-muted">first available · sold·new preferred</span>
							<span class="border border-border bg-bg px-1.5 py-0.5 text-xs text-text-muted">
								{md.price_color_specific ? 'this color' : 'all colors (most liquid)'}
							</span>
							{#if md.price_updated_at}
								<span class="text-xs text-text-muted"
									>synced {String(md.price_updated_at).slice(0, 10)}</span
								>
							{/if}
						</div>

						{#if md.price_from_base_mold}
							<div
								class="border border-warning/40 bg-warning/[0.08] px-2.5 py-1.5 text-sm text-text"
							>
								≈ Approximate — no market data for this exact print. Showing the base mold <span
									class="font-mono">{md.price_from_base_mold}</span
								>{md.price_from_base_name ? ` (${md.price_from_base_name})` : ''} price instead.
							</div>
						{/if}

						{#if price}
							<div class="overflow-x-auto">
								<table class="w-full border-collapse text-sm">
									<thead>
										<tr class="text-text-muted">
											<th class="border border-border px-2 py-1 text-left font-medium">Source</th>
											<th class="border border-border px-2 py-1 text-right font-medium">Avg</th>
											<th class="border border-border px-2 py-1 text-right font-medium">Wt avg</th>
											<th class="border border-border px-2 py-1 text-right font-medium">Min</th>
											<th class="border border-border px-2 py-1 text-right font-medium">Max</th>
											<th class="border border-border px-2 py-1 text-right font-medium">Qty</th>
											<th class="border border-border px-2 py-1 text-right font-medium">Lots</th>
										</tr>
									</thead>
									<tbody>
										{#each PRICE_BUCKETS as [key, label]}
											{@const b = (price[key] ?? {}) as Record<string, any>}
											<tr>
												<td class="border border-border px-2 py-1 text-text">{label}</td>
												<td class="border border-border px-2 py-1 text-right text-text tabular-nums"
													>{fmtPrice(b.avg)}</td
												>
												<td class="border border-border px-2 py-1 text-right text-text tabular-nums"
													>{fmtPrice(b.wavg)}</td
												>
												<td
													class="border border-border px-2 py-1 text-right text-text-muted tabular-nums"
													>{fmtPrice(b.min)}</td
												>
												<td
													class="border border-border px-2 py-1 text-right text-text-muted tabular-nums"
													>{fmtPrice(b.max)}</td
												>
												<td
													class="border border-border px-2 py-1 text-right text-text-muted tabular-nums"
													>{b.qty ?? '—'}</td
												>
												<td
													class="border border-border px-2 py-1 text-right text-text-muted tabular-nums"
													>{b.lots ?? '—'}</td
												>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{:else}
							<div class="text-text-muted">
								No price-guide rows for this part in the local catalog.
							</div>
						{/if}

						{#if bl}
							<div class="flex flex-wrap gap-x-4 gap-y-1 text-xs text-text-muted">
								{#if bl.item_no}<span>BL item {bl.item_no}</span>{/if}
								{#if bl.weight_g}<span>{bl.weight_g} g</span>{/if}
								{#if bl.dim_x_studs && bl.dim_y_studs}<span
										>{bl.dim_x_studs}×{bl.dim_y_studs} studs</span
									>{/if}
								{#if bl.year_released}<span>since {bl.year_released}</span>{/if}
								{#if bl.is_obsolete}<span>obsolete</span>{/if}
							</div>
						{/if}
					</div>
				</section>
			{/if}

			<!-- Arrival snapshot: full carousel frame at the instant the piece first
			     appeared on C4 (dropping in from C3). The catalog reference shot
			     lives in the Classification card, so this is just the one photo. -->
			{#if piece.drop_snapshot}
				{@const drop_src = dataImageUrl(piece.drop_snapshot) as string}
				<section class="border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
						Arrival snapshot
					</div>
					<div class="p-3">
						<button
							type="button"
							class="flex flex-col border border-border bg-bg text-left hover:border-primary/70"
							onclick={() => (zoomImage = { src: drop_src, label: 'At arrival' })}
						>
							<div class="flex h-40 w-40 items-center justify-center bg-white">
								<img
									src={drop_src}
									alt="arrival snapshot"
									class="h-full w-full cursor-zoom-in object-contain"
									loading="lazy"
								/>
							</div>
							<div class="px-2 py-1.5 text-xs text-text-muted">At arrival</div>
						</button>
					</div>
				</section>
			{/if}

			<!-- Classification requests: the parallel Brickognize calls (combined +
			     single-image variants). Each ran concurrently; the highest-confidence
			     "found" call wins and is marked applied. Shows what every request
			     returned, not just the winner, so a confused fused set vs. a clean
			     lone frame is visible at a glance. -->
			{#if attempts.length > 0}
				<section class="border border-border bg-surface">
					<div class="border-b border-border bg-bg px-3 py-2 text-sm font-medium text-text">
						Classification requests
						<span class="ml-2 text-text-muted">{attempts.length}</span>
					</div>
					<div class="flex flex-col gap-2 p-3">
						{#each attempts as a, ai (ai)}
							{@const open = expandedAttempts.has(ai)}
							{@const sent = attemptImages(a)}
							<div class={`border ${a.applied ? 'border-primary' : 'border-border'}`}>
								<button
									type="button"
									class={`flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left text-sm ${
										a.applied ? 'bg-primary/[0.08]' : 'bg-bg hover:bg-surface'
									}`}
									onclick={() => toggleAttempt(ai)}
								>
									{#if open}
										<ChevronDown class="h-4 w-4 shrink-0 text-text-muted" />
									{:else}
										<ChevronRight class="h-4 w-4 shrink-0 text-text-muted" />
									{/if}
									<span class="font-medium text-text">{attemptName(a)}</span>
									<span class="text-text-muted">{attemptInputs(a)}</span>
									<span
										class={`tabular-nums ${
											a.error
												? 'text-danger'
												: a.found
													? 'font-medium text-text'
													: 'text-text-muted'
										}`}
									>
										{attemptOutcome(a)}
									</span>
									{#if a.found && a.part_name}
										<span class="text-text-muted">{a.part_name}</span>
									{/if}
									{#if a.found && a.color_name}
										<span class="text-text-muted">· {a.color_name}</span>
									{/if}
									{#if a.error}
										<span class="text-text-muted">{a.error}</span>
									{/if}
									{#if a.duration_s != null}
										<span class="text-text-muted tabular-nums">{a.duration_s.toFixed(2)}s</span>
									{/if}
									{#if a.applied}
										<span
											class="ml-auto bg-primary px-1.5 py-0.5 text-xs font-semibold tracking-wider text-white uppercase"
											title="This request's result was applied to the piece"
										>
											Applied
										</span>
									{/if}
								</button>
								{#if open}
									<div class="flex flex-wrap gap-4 border-t border-border p-3">
										<!-- What was sent to Brickognize for this request -->
										<div class="flex flex-col gap-1.5">
											<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
												Sent ({sent.length})
											</div>
											{#if sent.length === 0}
												<div
													class="flex h-32 w-32 items-center justify-center border border-border bg-bg text-sm text-text-muted"
												>
													crops aged out
												</div>
											{:else}
												<div class="flex flex-wrap gap-2">
													{#each sent as crop (cropKey(crop))}
														<button
															type="button"
															class="flex flex-col border border-border bg-bg text-left hover:border-primary/70"
															onclick={() =>
																(zoomImage = { src: crop.src, label: formatCropLabel(crop) })}
														>
															<div class="h-32 w-32 bg-white">
																<img
																	src={crop.src}
																	alt={crop.role}
																	class="h-full w-full object-contain"
																	loading="lazy"
																/>
															</div>
															<div class="px-1.5 py-1 text-xs text-text-muted">
																{formatCropLabel(crop)}
															</div>
														</button>
													{/each}
												</div>
											{/if}
										</div>
										<!-- What Brickognize returned for this request -->
										<div class="flex flex-col gap-1.5">
											<div class="text-xs font-semibold tracking-wider text-text-muted uppercase">
												Result
											</div>
											{#if a.error}
												<div
													class="flex h-32 w-32 items-center justify-center border border-danger/40 bg-bg p-2 text-center text-sm text-danger"
												>
													{a.error}
												</div>
											{:else if a.found}
												<div class="flex gap-2">
													{#if a.preview_url}
														<button
															type="button"
															class="flex flex-col border border-border bg-bg text-left hover:border-primary/70"
															onclick={() =>
																(zoomImage = {
																	src: a.preview_url as string,
																	label: a.part_name ?? a.part_id ?? 'result'
																})}
														>
															<div class="h-32 w-32 bg-white">
																<img
																	src={a.preview_url}
																	alt="brickognize reference"
																	class="h-full w-full object-contain"
																	loading="lazy"
																/>
															</div>
														</button>
													{/if}
													<div class="flex flex-col gap-0.5 text-sm">
														<span class="font-medium text-text tabular-nums">{a.part_id}</span>
														{#if a.part_name}<span class="text-text-muted">{a.part_name}</span>{/if}
														{#if a.confidence != null}
															<span class="text-text-muted tabular-nums"
																>{(a.confidence * 100).toFixed(0)}% match</span
															>
														{/if}
														{#if a.color_name}<span class="text-text-muted"
																>Color: {a.color_name}</span
															>{/if}
													</div>
												</div>
											{:else}
												<div
													class="flex h-32 w-32 items-center justify-center border border-border bg-bg text-sm text-text-muted"
												>
													no match
												</div>
											{/if}
										</div>
									</div>
								{/if}
							</div>
						{/each}
					</div>
				</section>
			{/if}

					{#snippet cropOverlay(item: Thumb<CropEntry>)}
						{#if item.ref.used}
							<span
								class="absolute top-1 left-1 bg-primary px-1.5 py-0.5 text-xs font-semibold text-white"
								title="Shipped to Brickognize for classification"
							>
								Used
							</span>
						{/if}
						{#if item.ref.sharpness != null}
							<span
								class="absolute top-1 right-1 bg-text/80 px-1 py-0.5 text-xs font-semibold text-bg tabular-nums"
								title="Sharpness (Laplacian variance) — higher is sharper / less motion blur"
							>
								⌖ {formatSharpness(item.ref.sharpness)}
							</span>
						{/if}
						<span
							class="absolute bottom-1 left-1 bg-text/80 px-1 py-0.5 text-xs font-semibold text-bg"
							title="Channel this image came from"
						>
							{channelLabel(item.ref.channel)}
						</span>
						<ImageInfoBadge
							class="absolute right-1 bottom-1 z-10"
							src={item.src}
							rows={cropInfoRows(item.ref)}
						/>
					{/snippet}
			<!-- Image gallery + Brickognize reference -->
			<section class="border border-border bg-surface">
				<div
					class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm"
				>
					<div class="font-medium text-text">
						Classification burst
						<span class="ml-2 text-text-muted">{burstThumbs.length}</span>
					</div>
					<span class="text-sm text-text-muted">C4 · outlined = used for classification</span>
				</div>
				<div class="p-3">
					{#if burstThumbs.length === 0}
						<div class="text-sm text-text-muted">No burst frames for this piece.</div>
					{:else}
						<PieceThumbGrid
							items={burstThumbs}
							minPx={120}
							overlay={cropOverlay}
							onZoom={(t) => (zoomImage = { src: t.src, label: formatCropLabel(t.ref) })}
						/>
					{/if}
				</div>
			</section>

			<!-- The same physical piece as seen upstream, ranked by the piece-link
			     model. Outlined tiles were fused into the Brickognize request
			     alongside the burst; the rest are shown for review. -->
			<section class="border border-border bg-surface">
				<div
					class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm"
				>
					<div class="font-medium text-text">
						Other channels
						<span class="ml-2 text-text-muted">{otherChannelThumbs.length}</span>
					</div>
					<span class="text-sm text-text-muted">
						{#if linkMatchCount > 0}
							C2/C3 · ranked by match probability · outlined = used for classification
						{:else}
							C2/C3
						{/if}
					</span>
				</div>
				<div class="p-3">
					{#if otherChannelThumbs.length === 0}
						<div class="text-sm text-text-muted">
							No upstream views of this piece.
						</div>
					{:else}
						<PieceThumbGrid
							items={otherChannelThumbs}
							minPx={120}
							overlay={cropOverlay}
							onZoom={(t) => (zoomImage = { src: t.src, label: formatCropLabel(t.ref) })}
						/>
					{/if}
				</div>
			</section>

			<!-- Scratch reclassify: pick crops, re-run Brickognize (not recorded) -->
			{#if crops.length > 0}
				<ReclassifyPanel
					endpointBase={effectiveBase()}
					images={crops.map((c) => ({
						image: c.src,
						label: formatCropLabel(c),
						used: c.used
					}))}
				/>
			{/if}

			<!-- Drop burst: fashion-shoot sequence from the C3→C4 fall -->
			{#if burstFrames.length > 0}
				<section class="border border-border bg-surface">
					<div
						class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm"
					>
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
								<span
									class={`font-semibold tracking-wider uppercase ${burstRoleClass(selectedBurstFrame.role)}`}
								>
									{burstRoleLabel(selectedBurstFrame.role)}
								</span>
								<span class="tabular-nums">{formatAbsTs(selectedBurstFrame.captured_ts)}</span>
								<span class="text-text-muted"
									>· frame {selectedBurstIdx + 1} / {burstFrames.length}</span
								>
							</div>
						</div>
					{/if}
					<div class="flex flex-row gap-1 overflow-x-auto px-3 py-2">
						{#each burstFrames as frame, idx (frame.captured_ts + '|' + idx)}
							<button
								type="button"
								class={`flex h-32 flex-shrink-0 flex-col bg-bg text-left hover:border-primary/70 ${
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
					<div
						class="flex items-center justify-between border-b border-border bg-bg px-3 py-2 text-sm"
					>
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
						<TrackPathComposite globalId={piece.tracked_global_id} {usedCropTs} />
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
									<span class="absolute top-1.5 -left-[5px] h-2 w-2 bg-primary"></span>
									<span class="min-w-[12rem] text-sm text-text">{ev.label}</span>
									<span class="font-mono text-sm text-text-muted tabular-nums">
										{formatAbsTs(ev.ts)}
									</span>
									{#if idx > 0}
										<span class="font-mono text-xs text-text-muted tabular-nums">
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
