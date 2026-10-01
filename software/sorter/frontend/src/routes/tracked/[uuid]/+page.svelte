<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/state';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import AppShell from '$lib/components/AppShell.svelte';
	import ImageInfoBadge from '$lib/components/ImageInfoBadge.svelte';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import PieceInfoCard from '$lib/components/pieces/PieceInfoCard.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Disclosure from '$lib/components/ui/Disclosure.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
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
	import { pieceStore, type PieceDetailEnvelope, type PieceSummary } from '$lib/pieces';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';


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

	let _refetchedForUpdatedAt = 0;
	let _refetchTimer: ReturnType<typeof setTimeout> | null = null;

	// SvelteKit reuses this component when navigating /tracked/<a> ->
	// /tracked/<b>, so none of the per-piece state above resets on its own.
	// Without this, _fetchStatus stays 'ok' (the new piece never fetches its
	// detail, so it renders the OLD piece's image sets) and
	// _refetchedForUpdatedAt — an absolute timestamp from the old piece — can
	// block the refetch effect below for the new piece entirely.
	let _resetForUuid = '';
	$effect(() => {
		if (uuid === _resetForUuid) return;
		_resetForUuid = uuid;
		_stickyPiece = null;
		_fetchedPiece = null;
		_diskSummary = null;
		_diskImages = [];
		_refetchedForUpdatedAt = 0;
		if (_refetchTimer !== null) {
			clearTimeout(_refetchTimer);
			_refetchTimer = null;
		}
		_fetchStatus = 'idle';
	});

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

	// The detail fetch is one-shot per UUID, but a LIVE piece keeps evolving
	// after the page opens: the burst grows, classification lands, used flags
	// settle, link matches attach. The slim WS payload signals each change via
	// updated_at without carrying the image sets — so when it moves past the
	// snapshot we fetched, re-arm the fetch. Guarded by recording the trigger
	// value first, so a fetch that returns older data can't loop. Trailing
	// 750ms debounce: emits can arrive in quick bursts and every re-fetch
	// pulls the full multi-MB b64 payload, so wait for a quiet gap instead of
	// re-fetching on each tick.
	$effect(() => {
		const upd = _stickyPiece?.updated_at ?? 0;
		if (upd <= 0) return;
		if (_fetchStatus === 'idle' || _fetchStatus === 'loading') return;
		if (upd <= _refetchedForUpdatedAt) return;
		_refetchedForUpdatedAt = upd;
		if (_refetchTimer !== null) clearTimeout(_refetchTimer);
		_refetchTimer = setTimeout(() => {
			_refetchTimer = null;
			_fetchStatus = 'idle';
		}, 750);
	});

	let showRawJson = $state(false);
	let zoomImage = $state<{ src: string; label: string } | null>(null);

	// Tick so relative timestamps refresh.
	let now_tick = $state(0);
	let timerId: ReturnType<typeof setInterval> | null = null;
	onMount(() => {
		timerId = setInterval(() => (now_tick += 1), 1000);
	});
	onDestroy(() => {
		if (timerId !== null) clearInterval(timerId);
		if (_refetchTimer !== null) clearTimeout(_refetchTimer);
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

	const TS_TOLERANCE_S = 0.005;

	function tsWasUsed(captured_ts: number, usedList: number[]): boolean {
		for (const t of usedList) {
			if (Math.abs(t - captured_ts) <= TS_TOLERANCE_S) return true;
		}
		return false;
	}

	// Stable image keys keep live piece updates from remounting the gallery.
	function cropKey(c: CropEntry): string {
		return `${c.role}|${c.ts ?? 'no-ts'}|${c.src}`;
	}

	let _cachedCrops = $state<CropEntry[]>([]);
	let _cachedCropsSig = '';

	$effect(() => {
		if (!piece) {
			if (_cachedCropsSig !== '') {
				_cachedCropsSig = '';
				_cachedCrops = [];
			}
			return;
		}
		const entries: CropEntry[] = [];
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

		// Older piece records may still carry chamber snapshots.
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

		const sig = entries.map((c) => `${cropKey(c)}|${c.used ? 1 : 0}`).join(';');
		if (sig !== _cachedCropsSig) {
			_cachedCropsSig = sig;
			_cachedCrops = entries;
		}
	});

	const crops = $derived(_cachedCrops);

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
		if (role === 'recognition_capture') return 'Recognition capture';
		if (role === 'link_match') return 'Link match (C2/C3)';
		if (role === 'classification_top') return 'Classification top';
		if (role === 'classification_bottom') return 'Classification bottom';
		if (role === 'carousel') return 'Classification channel';
		if (role === 'c_channel_2') return 'C-channel 2';
		if (role === 'c_channel_3') return 'C-channel 3';
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
		if (conf == null) return 'text-ink-muted';
		const pct = conf * 100;
		if (pct >= 90) return 'text-success-ink';
		if (pct >= 80) return 'text-warning-ink';
		if (pct >= 60) return 'text-warning-ink/70';
		return 'text-danger-ink';
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
				valueClass: `font-semibold num ${confidenceClass(o.confidence)}`
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
				valueClass: `font-semibold num ${confidenceClass(o.color_confidence)}`
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
			valueClass: 'font-mono num text-ink'
		});
		if (o.est_value != null) {
			rows.push({
				label: 'Est. value',
				value: fmtPrice(o.est_value),
				valueClass: 'num text-ink'
			});
		}
		if (o.run_id) rows.push({ label: 'Run', value: o.run_id, mono: true });
		if (o.tracked_global_id != null) {
			rows.push({
				label: 'Tracker',
				value: String(o.tracked_global_id),
				valueClass: 'font-mono num text-ink'
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

	// Catalog reference shot for the identified part, as Brickognize returned
	// it. Shown once, in the Classification card, the same way the disk view
	// shows `preview_url`.
	const refImageSrc = $derived<string | null>(piece?.brickognize_preview_url ?? null);

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

	// The two sources, shown separately: the C4 burst and
	// the upstream C2/C3 views of the same piece. In both, `used` (a stroke on
	// the tile) means the image was actually shipped to Brickognize in the
	// request whose result was applied.
	const burstThumbs = $derived<Thumb<CropEntry>[]>(
		crops.filter((c) => c.role === 'recognition_capture').map(toThumb)
	);

	// Link matches are ranked by the model's probability.
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
	<title>Piece {uuid.slice(0, 8)} - Sorter</title>
</svelte:head>

{#snippet thumbCrop(src: string, alt: string, label: string, onclick: () => void)}
	<button
		type="button"
		class="flex flex-col gap-1 rounded-control p-1 text-left transition-colors hover:bg-hover"
		{onclick}
	>
		<img {src} {alt} class="size-32 rounded-item object-contain" loading="lazy" />
		{#if label}<span class="px-1 text-xs text-ink-muted">{label}</span>{/if}
	</button>
{/snippet}

<AppShell>
	<div class="mx-auto flex w-full max-w-[1600px] flex-col gap-(--gap-panels) px-4 py-6 sm:px-6">
		<PageHeader title="Piece {uuid.slice(0, 8)}">
			{#snippet actions()}
				<Button icon={ArrowLeft} href="/records">Back to the records</Button>
			{/snippet}
			<div class="flex flex-wrap items-center gap-2">
				{#if piece}
					{#if piece.stage === 'distributed'}
						<Badge>Distributed</Badge>
					{:else if piece.stage === 'distributing'}
						<Badge tone="primary">Distributing</Badge>
					{/if}
					<PieceStatusBadge
						status={piece.classification_status}
						requestFailed={Boolean(piece.request_failed)}
						dead={Boolean(piece.dead)}
					/>
				{:else if _diskSummary}
					<PieceStatusBadge status={_diskSummary.classification_status} dead={Boolean(_diskSummary.dead)} />
				{/if}
			</div>
		</PageHeader>

		{#if !piece}
			{#if _fetchStatus === 'summary_only' && _diskSummary}
				{@const ds = _diskSummary}
				<section class="grid grid-cols-1 gap-(--gap-panels) lg:grid-cols-2">
					<PieceInfoCard
						title="Classification"
						rows={classificationRows(ds)}
						image={ds.preview_url}
						imageAlt="Brickognize reference"
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

				{#if diskThumbs.length > 0}
					<Panel title="Stored images" description="{diskThumbs.length} on disk.">
						<PieceThumbGrid
							items={diskThumbs}
							minPx={120}
							onZoom={(t) => (zoomImage = { src: t.src, label: t.ref.source })}
						/>
					</Panel>
				{/if}
			{:else if _fetchStatus === 'loading' || _fetchStatus === 'idle'}
				<Panel>
					<p class="flex items-center gap-2 text-sm text-ink-muted">
						<Spinner size={16} />
						Loading the piece
					</p>
				</Panel>
			{:else if _fetchStatus === 'not_found'}
				<EmptyState title="No trace of this piece">
					It isn't in backend memory, the durable piece records or the on-disk image store. Go back to the
					<a href="/records" class="text-primary-ink hover:underline">piece records</a>.
				</EmptyState>
			{:else}
				<Alert tone="danger" title="This piece did not load">
					Check the backend connection and try again.
				</Alert>
			{/if}
		{:else}
			<!-- Identity and classification summary -->
			<section class="grid grid-cols-1 gap-(--gap-panels) lg:grid-cols-2">
				<PieceInfoCard
					title="Classification"
					rows={classificationRows({
						part_id: piece.part_id,
						part_name: piece.part_name ?? null,
						color_name: piece.color_name,
						color_provider: piece.color_provider,
						mold_provider: piece.mold_provider,
						category_id: piece.category_id,
						confidence: piece.confidence,
						color_confidence: piece.color_confidence,
						source_view: piece.brickognize_source_view
					})}
					image={refImageSrc}
					imageAlt="Brickognize reference"
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

			<!-- Pricing: every BrickLink bucket from the Hive catalog. The headline
			     `moving_avg_price` (what routing uses) is the first non-empty of these,
			     sold-new preferred; the table shows all four so you can see whatever
			     source actually exists for this part. -->
			{#if piece.piece_metadata}
				{@const md = piece.piece_metadata as Record<string, any>}
				{@const price = (md.price ?? null) as Record<string, any> | null}
				{@const bl = (md.bricklink ?? null) as Record<string, any> | null}
				<Panel
					title="Pricing"
					description="From the Hive catalog{md.price_currency ? `, BrickLink ${md.price_currency}` : ''}."
					flush
				>
					<div class="flex flex-col gap-3 px-(--pad-panel) pb-4 text-sm">
						<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
							<span class="text-ink-muted">Moving average, used for routing</span>
							<span class="num text-base font-semibold text-ink">
								{typeof md.moving_avg_price === 'number' ? fmtPrice(md.moving_avg_price) : '—'}
							</span>
							<Badge>{md.price_color_specific ? 'This color' : 'All colors (most liquid)'}</Badge>
							<span class="text-xs text-ink-muted">First available, sold new preferred.</span>
							{#if md.price_updated_at}
								<span class="text-xs text-ink-muted">Synced {String(md.price_updated_at).slice(0, 10)}</span>
							{/if}
						</div>

						{#if md.price_from_base_mold}
							<Alert tone="warning" title="Approximate">
								There is no market data for this exact print. This shows the base mold
								<span class="font-mono">{md.price_from_base_mold}</span>{md.price_from_base_name
									? ` (${md.price_from_base_name})`
									: ''} price instead.
							</Alert>
						{/if}
					</div>

					{#if price}
						<div class="overflow-x-auto">
							<table class="data-table">
								<thead>
									<tr>
										<th>Source</th>
										<th class="num">Avg</th>
										<th class="num">Weighted avg</th>
										<th class="num">Min</th>
										<th class="num">Max</th>
										<th class="num">Qty</th>
										<th class="num">Lots</th>
									</tr>
								</thead>
								<tbody>
									{#each PRICE_BUCKETS as [key, label]}
										{@const b = (price[key] ?? {}) as Record<string, any>}
										<tr>
											<td>{label}</td>
											<td class="num">{fmtPrice(b.avg)}</td>
											<td class="num">{fmtPrice(b.wavg)}</td>
											<td class="num text-ink-muted">{fmtPrice(b.min)}</td>
											<td class="num text-ink-muted">{fmtPrice(b.max)}</td>
											<td class="num text-ink-muted">{b.qty ?? '—'}</td>
											<td class="num text-ink-muted">{b.lots ?? '—'}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						</div>
					{:else}
						<p class="px-(--pad-panel) pb-4 text-sm text-ink-muted">
							No price-guide rows for this part in the Hive catalog.
						</p>
					{/if}

					{#if bl}
						<div class="flex flex-wrap gap-x-4 gap-y-1 px-(--pad-panel) py-3 text-xs text-ink-muted">
							{#if bl.item_no}<span>BL item {bl.item_no}</span>{/if}
							{#if bl.weight_g}<span>{bl.weight_g} g</span>{/if}
							{#if bl.dim_x_studs && bl.dim_y_studs}<span>{bl.dim_x_studs}×{bl.dim_y_studs} studs</span>{/if}
							{#if bl.year_released}<span>since {bl.year_released}</span>{/if}
							{#if bl.is_obsolete}<span>obsolete</span>{/if}
						</div>
					{/if}
				</Panel>
			{/if}

			<!-- Arrival snapshot: the full carousel frame at the instant the piece first
			     appeared on C4 (dropping in from C3). The catalog reference shot lives in
			     the Classification panel, so this is just the one photo. -->
			{#if piece.drop_snapshot}
				{@const drop_src = dataImageUrl(piece.drop_snapshot) as string}
				<Panel title="Arrival snapshot">
					<button
						type="button"
						class="flex flex-col gap-1 rounded-control p-1 text-left transition-colors hover:bg-hover"
						onclick={() => (zoomImage = { src: drop_src, label: 'At arrival' })}
					>
						<img
							src={drop_src}
							alt="arrival snapshot"
							class="size-40 cursor-zoom-in rounded-item bg-surface object-contain"
							loading="lazy"
						/>
						<span class="px-1 text-xs text-ink-muted">At arrival</span>
					</button>
				</Panel>
			{/if}

			<!-- Classification requests: the parallel Brickognize calls (combined and
			     single-image variants). Each ran concurrently; the highest-confidence
			     "found" call wins and is marked applied. It shows what every request
			     returned, not just the winner, so a confused fused set against a clean
			     lone frame is visible at a glance. -->
			{#if attempts.length > 0}
				<Panel
					title="Classification requests"
					description="{attempts.length} sent in parallel; the best match was applied."
					flush
				>
					<ul class="divide-y divide-line">
						{#each attempts as a, ai (ai)}
							{@const open = expandedAttempts.has(ai)}
							{@const sent = attemptImages(a)}
							<li class={a.applied ? 'bg-primary-soft' : ''}>
								<button
									type="button"
									aria-expanded={open}
									class="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-(--pad-panel) py-3 text-left text-sm transition-colors hover:bg-hover"
									onclick={() => toggleAttempt(ai)}
								>
									{#if open}
										<ChevronDown size={16} class="shrink-0 text-ink-muted" />
									{:else}
										<ChevronRight size={16} class="shrink-0 text-ink-muted" />
									{/if}
									<span class="font-medium text-ink">{attemptName(a)}</span>
									<span class="text-ink-muted">{attemptInputs(a)}</span>
									<span
										class="num {a.error ? 'text-danger-ink' : a.found ? 'font-medium text-ink' : 'text-ink-muted'}"
									>
										{attemptOutcome(a)}
									</span>
									{#if a.found && a.part_name}<span class="text-ink-muted">{a.part_name}</span>{/if}
									{#if a.found && a.color_name}<span class="text-ink-muted">· {a.color_name}</span>{/if}
									{#if a.error}<span class="text-ink-muted">{a.error}</span>{/if}
									{#if a.duration_s != null}
										<span class="num text-ink-muted">{a.duration_s.toFixed(2)}s</span>
									{/if}
									{#if a.applied}
										<span class="ml-auto" title="This request's result was applied to the piece">
											<Badge tone="primary">Applied</Badge>
										</span>
									{/if}
								</button>
								{#if open}
									<div class="flex flex-wrap gap-6 px-(--pad-panel) pb-4">
										<!-- What was sent to Brickognize for this request -->
										<div class="flex flex-col gap-2">
											<div class="label">Sent ({sent.length})</div>
											{#if sent.length === 0}
												<div class="flex size-32 items-center justify-center rounded-control bg-well text-sm text-ink-muted">
													Crops aged out
												</div>
											{:else}
												<div class="flex flex-wrap gap-2">
													{#each sent as crop (cropKey(crop))}
														{@render thumbCrop(crop.src, crop.role, formatCropLabel(crop), () =>
															(zoomImage = { src: crop.src, label: formatCropLabel(crop) })
														)}
													{/each}
												</div>
											{/if}
										</div>
										<!-- What Brickognize returned for this request -->
										<div class="flex flex-col gap-2">
											<div class="label">Result</div>
											{#if a.error}
												<div class="flex size-32 items-center justify-center rounded-control bg-danger-soft p-2 text-center text-sm text-danger-ink">
													{a.error}
												</div>
											{:else if a.found}
												<div class="flex gap-3">
													{#if a.preview_url}
														{@render thumbCrop(a.preview_url, 'Brickognize reference', '', () =>
															(zoomImage = {
																src: a.preview_url as string,
																label: a.part_name ?? a.part_id ?? 'result'
															})
														)}
													{/if}
													<div class="flex flex-col gap-0.5 text-sm">
														<span class="num font-medium text-ink">{a.part_id}</span>
														{#if a.part_name}<span class="text-ink-muted">{a.part_name}</span>{/if}
														{#if a.confidence != null}
															<span class="num text-ink-muted">{(a.confidence * 100).toFixed(0)}% match</span>
														{/if}
														{#if a.color_name}<span class="text-ink-muted">Color: {a.color_name}</span>{/if}
													</div>
												</div>
											{:else}
												<div class="flex size-32 items-center justify-center rounded-control bg-well text-sm text-ink-muted">
													No match
												</div>
											{/if}
										</div>
									</div>
								{/if}
							</li>
						{/each}
					</ul>
				</Panel>
			{/if}

			{#snippet cropOverlay(item: Thumb<CropEntry>)}
				<!-- Chips over a picture sit in a dark subtree. -->
				{#if item.ref.used}
					<span
						class="dark absolute top-1 left-1 rounded-badge bg-scrim px-1 text-xs font-medium text-ink"
						title="Shipped to Brickognize for classification"
					>
						Used
					</span>
				{/if}
				{#if item.ref.sharpness != null}
					<span
						class="dark num absolute top-1 right-1 rounded-badge bg-scrim px-1 text-xs font-medium text-ink"
						title="Sharpness (Laplacian variance): higher is sharper, with less motion blur"
					>
						⌖ {formatSharpness(item.ref.sharpness)}
					</span>
				{/if}
				<span
					class="dark absolute bottom-1 left-1 rounded-badge bg-scrim px-1 text-xs font-medium text-ink"
					title="Channel this image came from"
				>
					{channelLabel(item.ref.channel)}
				</span>
				<ImageInfoBadge class="absolute right-1 bottom-1 z-10" src={item.src} rows={cropInfoRows(item.ref)} />
			{/snippet}

			<!-- The classification burst -->
			<Panel title="Classification burst" description="{burstThumbs.length} frames from C4. Tinted frames were used for classification.">
				{#if burstThumbs.length === 0}
					<p class="text-sm text-ink-muted">No burst frames for this piece.</p>
				{:else}
					<PieceThumbGrid
						items={burstThumbs}
						minPx={120}
						overlay={cropOverlay}
						onZoom={(t) => (zoomImage = { src: t.src, label: formatCropLabel(t.ref) })}
					/>
				{/if}
			</Panel>

			<!-- The same physical piece as seen upstream, ranked by the piece-link
			     model. Tinted tiles were fused into the Brickognize request alongside
			     the burst; the rest are shown for review. -->
			<Panel
				title="Other channels"
				description="{otherChannelThumbs.length} views from C2 and C3{linkMatchCount > 0
					? ', ranked by match probability. Tinted views were used for classification'
					: ''}."
			>
				{#if otherChannelThumbs.length === 0}
					<p class="text-sm text-ink-muted">No upstream views of this piece.</p>
				{:else}
					<PieceThumbGrid
						items={otherChannelThumbs}
						minPx={120}
						overlay={cropOverlay}
						onZoom={(t) => (zoomImage = { src: t.src, label: formatCropLabel(t.ref) })}
					/>
				{/if}
			</Panel>

			<!-- Scratch reclassify: pick crops, re-run Brickognize (not recorded) -->
			{#if crops.length > 0}
				<Panel>
					<ReclassifyPanel
						endpointBase={effectiveBase()}
						images={crops.map((c) => ({
							image: c.src,
							label: formatCropLabel(c),
							used: c.used
						}))}
					/>
				</Panel>
			{/if}

			<!-- Lifecycle timeline -->
			<Panel title="Lifecycle timeline">
				{#if timeline.length === 0}
					<p class="text-sm text-ink-muted">No lifecycle events recorded yet.</p>
				{:else}
					{@const anchor = timeline[0].ts}
					<ol class="flex flex-col">
						{#each timeline as ev, idx (idx)}
							<li class="relative flex items-baseline gap-3 border-l border-line pb-1.5 pl-4">
								<span class="absolute top-1.5 -left-[3.5px] size-1.5 bg-primary"></span>
								<span class="min-w-[12rem] text-sm text-ink">{ev.label}</span>
								<span class="num font-mono text-sm text-ink-muted">{formatAbsTs(ev.ts)}</span>
								{#if idx > 0}
									<span class="num font-mono text-xs text-ink-muted">{formatRelSec(ev.ts, anchor)}</span>
								{/if}
							</li>
						{/each}
					</ol>
				{/if}
			</Panel>

			<!-- Raw JSON -->
			<Panel flush>
				<Disclosure title="Raw JSON" bind:open={showRawJson}>
					<pre class="mx-(--pad-panel) max-h-96 overflow-auto rounded-control bg-well p-3 text-xs text-ink-muted">{JSON.stringify(
							piece,
							null,
							2
						)}</pre>
				</Disclosure>
			</Panel>
		{/if}
	</div>
</AppShell>

<Modal
	open={zoomImage !== null}
	title={zoomImage?.label ?? 'Image'}
	size="lg"
	onclose={() => (zoomImage = null)}
>
	{#if zoomImage}
		<img src={zoomImage.src} alt={zoomImage.label} class="mx-auto max-h-[70vh] max-w-full object-contain" />
	{/if}
</Modal>
