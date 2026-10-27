<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { afterNavigate } from '$app/navigation';
	import { page } from '$app/state';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import ChevronDown from '@lucide/svelte/icons/chevron-down';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import AppShell from '$lib/components/AppShell.svelte';
	import PieceStatusBadge from '$lib/components/PieceStatusBadge.svelte';
	import ReclassifyPanel from '$lib/components/ReclassifyPanel.svelte';
	import PieceOverview from '$lib/components/pieces/PieceOverview.svelte';
	import PiecePredictions from '$lib/components/pieces/PiecePredictions.svelte';
	import PieceProblems from '$lib/components/pieces/PieceProblems.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import Disclosure from '$lib/components/ui/Disclosure.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import KeyValue from '$lib/components/ui/KeyValue.svelte';
	import Modal from '$lib/components/ui/Modal.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import PieceThumbGrid from '$lib/components/pieces/PieceThumbGrid.svelte';
	import type { Fact, Frame, Thumb } from '$lib/components/pieces/types';
	import {
		diskToDisplay,
		fetchDiskImages,
		fetchDiskLinkImages,
		type DisplayImage
	} from '$lib/components/records/piece-images';
	import { getMachineContext } from '$lib/machines/context';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { KnownObjectData, ClassificationAttempt } from '$lib/api/events';
	import {
		fetchLegoColors,
		findLegoColor,
		pieceStore,
		type PieceDetailEnvelope,
		type PiecePrediction,
		type PieceSummary,
		type PredictionImage
	} from '$lib/pieces';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';

	// Back to the records goes to where the list was, with its filters, page and
	// scroll, when that is where this page was opened from.
	let cameFromRecords = false;
	afterNavigate(({ from }) => {
		cameFromRecords = from?.url.pathname.startsWith('/records') ?? false;
	});
	function backToRecords(event: MouseEvent) {
		if (!cameFromRecords) return;
		event.preventDefault();
		history.back();
	}

	const ctx = getMachineContext();
	onMount(() => {
		void sortingProfileStore.load();
		// The color swatches beside predicted colors.
		void fetchLegoColors(effectiveBase()).catch(() => {});
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
	// The machine's record of the piece, with the operator's answers: what the
	// review is about.
	let _summary = $state<PieceSummary | null>(null);
	let _diskImages = $state<DisplayImage[]>([]);
	// Every prediction made for the piece, from every source.
	let _predictions = $state<PiecePrediction[]>([]);

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
		_summary = null;
		_diskImages = [];
		_predictions = [];
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
				_predictions = env.predictions ?? [];
				_summary = env.summary ?? null;
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

	// A predicted-from image, from the piece in memory or the images on disk;
	// null once it has aged out.
	function predictionImageSrc(image: PredictionImage): string | null {
		const link = image.set === 'link';
		if (_fetchedPiece) {
			const set = link ? _fetchedPiece.link_match_image_set : _fetchedPiece.recognition_image_set;
			return dataImageUrl(set?.[image.seq]?.image);
		}
		const hit = _diskImages.find(
			(d) => (d.source === 'link_match') === link && d.seq === image.seq
		);
		return hit?.src ?? null;
	}

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

	// --- The top card ---------------------------------------------------------
	// The live (in-memory) and disk-fallback views describe the same piece from
	// two payload shapes. Both normalize into this and render through
	// PieceOverview, so the two views can't drift apart.
	type FactSource = {
		part_id?: string | null;
		part_name?: string | null;
		color_id?: string | null;
		color_name?: string | null;
		mold_provider?: string | null;
		color_provider?: string | null;
		confidence?: number | null;
		color_confidence?: number | null;
		category_id?: string | null;
		bin_label: string;
		stage?: string | null;
		value?: number | null;
		seen_at?: number | null;
	};

	// What a piece is called while it has no part: what became of it.
	function unnamed(status: string | null | undefined): string {
		if (status === 'pending' || status === 'classifying') return 'Waiting for the result';
		if (status === 'multi_drop_fail') return 'Several pieces dropped together';
		if (status === 'failed') return 'Identification failed';
		if (status === 'unknown' || status === 'not_found') return 'Not identified';
		return 'Unidentified piece';
	}

	function percent(v: number | null | undefined): string | null {
		return typeof v === 'number' ? `${(v * 100).toFixed(0)}%` : null;
	}

	// Mold and color are scored by (potentially) different providers, so each
	// confidence sits with the source that produced it.
	function overviewFacts(o: FactSource): Fact[] {
		const mold = [providerLabel(o.mold_provider), percent(o.confidence)].filter(Boolean);
		const colorName = o.color_name && o.color_name !== 'Any Color' ? o.color_name : null;
		const color = findLegoColor(o.color_id, o.color_name);
		const colorBy = [providerLabel(o.color_provider), percent(o.color_confidence)].filter(Boolean);
		const facts: Fact[] = [
			{
				label: 'Mold',
				value: mold.join(' · ') || '—',
				valueClass: `font-medium num ${confidenceClass(o.confidence)}`,
				title: 'Which service identified the part, and how sure it was'
			},
			{
				label: 'Color',
				value: colorName ? [colorName, ...colorBy].join(' · ') : '—',
				swatch: color?.hex ?? null,
				title: 'The color and which service gave it, and how sure it was'
			},
			{
				label: 'Category',
				value: o.category_id ? (sortingProfileStore.getCategoryName(o.category_id) ?? '—') : '—'
			},
			{
				label: 'Bin',
				value: o.stage ? `${o.bin_label} · ${o.stage}` : o.bin_label,
				mono: true,
				title: 'Layer, section and bin the machine put it in (counted from 0)'
			}
		];
		if (o.value != null) {
			facts.push({ label: 'Value', value: fmtPrice(o.value), valueClass: 'num text-ink' });
		}
		if (o.seen_at != null) {
			facts.push({
				label: 'Seen',
				value: new Date(o.seen_at * 1000).toLocaleString(undefined, {
					month: 'short',
					day: 'numeric',
					hour: 'numeric',
					minute: '2-digit',
					second: '2-digit'
				})
			});
		}
		return facts;
	}

	// Catalog reference shot for the identified part, as Brickognize returned
	// it. Shown once, in the Classification card, the same way the disk view
	// shows `preview_url`.
	const refImageSrc = $derived<string | null>(piece?.brickognize_preview_url ?? null);

	// Destination bin reads as the discard bin for pieces that were never
	// identified — they still get routed, just not to a part-specific bin.
	function liveBinLabel(): string {
		if (piece?.destination_bin) return formatBin(piece.destination_bin);
		// The live payload may not carry it once the piece is distributed; the
		// machine's record does.
		if (_summary?.bin) return formatSummaryBin(_summary.bin);
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

	// The burst the camera took, for the top card: all of it, small, the frames that
	// produced the result tinted.
	function frameLabel(parts: (string | false | null)[]): string {
		return parts.filter(Boolean).join(' · ');
	}

	const overviewFrames = $derived<Frame[]>(
		crops
			.filter((c) => c.role === 'recognition_capture')
			.map((c) => ({
				key: cropKey(c),
				src: c.src,
				label: frameLabel([formatCropLabel(c), formatAbsTs(c.ts), c.used && 'used for the result']),
				used: c.used,
				channel: channelLabel(c.channel),
				sharpness:
					c.sharpness != null && Number.isFinite(c.sharpness) ? formatSharpness(c.sharpness) : null
			}))
	);

	// A piece no longer in memory has its stored images instead.
	const diskFrames = $derived<Frame[]>(
		_diskImages
			.filter((img) => img.source !== 'link_match')
			.map((img, i) => ({
				key: String(i),
				src: img.src,
				label: frameLabel([
					sourceLabel(img.source, img.channel),
					img.used && 'used for the result'
				]),
				used: img.used,
				channel: img.source === 'c4_burst' ? 'C4' : channelLabel(img.channel),
				sharpness: null
			}))
	);
	const diskOtherThumbs = $derived(diskThumbs.filter((t) => t.ref.source === 'link_match'));

	const liveFacts = $derived<Fact[]>(
		piece
			? overviewFacts({
					part_id: piece.part_id,
					part_name: piece.part_name ?? null,
					color_id: piece.color_id ?? null,
					color_name: piece.color_name,
					mold_provider: piece.mold_provider,
					color_provider: piece.color_provider,
					confidence: piece.confidence,
					color_confidence: piece.color_confidence,
					category_id: piece.category_id,
					bin_label: liveBinLabel(),
					stage: piece.stage,
					value:
						typeof (piece.piece_metadata as Record<string, unknown> | undefined)
							?.moving_avg_price === 'number'
							? ((piece.piece_metadata as Record<string, unknown>).moving_avg_price as number)
							: null,
					seen_at: piece.created_at
				})
			: []
	);
	const diskFacts = $derived<Fact[]>(
		_diskSummary
			? overviewFacts({
					part_id: _diskSummary.part_id,
					part_name: _diskSummary.part_name,
					color_id: _diskSummary.color_id,
					color_name: _diskSummary.color_name,
					mold_provider: _diskSummary.mold_provider,
					color_provider: _diskSummary.color_provider,
					confidence: _diskSummary.confidence,
					color_confidence: _diskSummary.color_confidence,
					category_id: _diskSummary.category_id,
					bin_label: formatSummaryBin(_diskSummary.bin),
					value: _diskSummary.est_value,
					seen_at: _diskSummary.seen_at
				})
			: []
	);

	// An answer in the review: the page's record of the piece takes it, and the
	// dashboard's recent pieces hear of it.
	function onReviewed(summary: PieceSummary) {
		_summary = { ...(_summary ?? { uuid }), ...summary };
		const mid = ctx.machine?.identity?.machine_id ?? null;
		if (mid) pieceStore.upsertFromRest(mid, [summary]);
	}

	// What the details say before they are opened.
	const appliedAttempt = $derived(attempts.find((a) => a.applied) ?? null);
	const requestsHelp = $derived(
		`${attempts.length} sent in parallel${appliedAttempt ? `; applied: ${attemptName(appliedAttempt)}, ${attemptOutcome(appliedAttempt)}` : ''}`
	);
	const timelineHelp = $derived(
		timeline.length > 1
			? `${timeline.length} events over ${formatRelSec(timeline[timeline.length - 1].ts, timeline[0].ts).replace('+', '')}`
			: ''
	);
	const pricing = $derived.by(() => {
		const md = (piece?.piece_metadata ?? null) as Record<string, any> | null;
		return md && (md.price || md.moving_avg_price != null) ? md : null;
	});
	const pricingHelp = $derived(
		pricing
			? `${typeof pricing.moving_avg_price === 'number' ? fmtPrice(pricing.moving_avg_price) : '—'} moving average, ${pricing.price_color_specific ? 'this color' : 'all colors'}`
			: ''
	);
	const recordFacts = $derived.by(() => {
		const rows: { label: string; value: string; mono?: boolean }[] = [];
		if (piece) {
			if (piece.stage) rows.push({ label: 'Stage', value: piece.stage });
			if (piece.tracked_global_id != null) {
				rows.push({ label: 'Tracker', value: String(piece.tracked_global_id), mono: true });
			}
			if (piece.brickognize_source_view) {
				rows.push({ label: 'Source view', value: piece.brickognize_source_view });
			}
			if (piece.updated_at != null) {
				rows.push({
					label: 'Last update',
					value: `${formatAbsTs(piece.updated_at)} (${formatRelativeTime(piece.updated_at)})`
				});
			}
		} else if (_diskSummary) {
			if (_diskSummary.run_id) rows.push({ label: 'Run', value: _diskSummary.run_id, mono: true });
			if (_diskSummary.recorded_at != null) {
				rows.push({
					label: 'Recorded',
					value: new Date(_diskSummary.recorded_at * 1000).toLocaleString()
				});
			}
		}
		return rows;
	});

	// Which of the details are open: closed ones draw nothing.
	let openRequests = $state(false);
	let openChannels = $state(false);
	let openPricing = $state(false);
	let openTimeline = $state(false);
	let openReclassify = $state(false);
</script>

<svelte:head>
	<title>Piece {uuid.slice(0, 8)} - Sorter</title>
</svelte:head>

{#snippet thumbCrop(src: string, alt: string, label: string, onclick: () => void)}
	<ImageZoom {src} label={label || alt}>
		<button
			type="button"
			class="flex flex-col gap-1 rounded-control p-1 text-left transition-colors hover:bg-hover"
			{onclick}
		>
			<img {src} {alt} class="size-24 rounded-item object-contain" loading="lazy" />
			{#if label}<span class="px-1 text-xs text-ink-muted">{label}</span>{/if}
		</button>
	</ImageZoom>
{/snippet}

<AppShell>
	<div class="mx-auto flex w-full max-w-[1600px] flex-col gap-(--gap-panels) px-4 py-4 sm:px-6">
		<!-- The way back is first, at the left; then which piece this is. -->
		<header class="flex flex-wrap items-center gap-x-4 gap-y-2">
			<Button icon={ArrowLeft} href="/records/pieces" onclick={backToRecords}>
				Back to the records
			</Button>
			<h1 class="text-xl font-semibold tracking-tight text-ink">Piece {uuid.slice(0, 8)}</h1>
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
					<PieceStatusBadge
						status={_diskSummary.classification_status}
						dead={Boolean(_diskSummary.dead)}
					/>
				{/if}
			</div>
		</header>

		{#if !piece}
			{#if _fetchStatus === 'summary_only' && _diskSummary}
				{@const ds = _diskSummary}
				<PieceOverview
					name={ds.part_name ?? ds.part_id ?? unnamed(ds.classification_status)}
					partId={ds.part_name ? (ds.part_id ?? null) : null}
					frames={diskFrames}
					framesNote="{diskFrames.length} stored frames. Tinted frames produced the result."
					reference={ds.preview_url ?? null}
					facts={diskFacts}
					summary={_summary}
					endpointBase={effectiveBase()}
					{onReviewed}
					onZoom={(src, label) => (zoomImage = { src, label })}
				/>

				<PieceProblems problems={_summary?.problems} />

				{#if _predictions.length > 0}
					<PiecePredictions
						predictions={_predictions}
						imageSrc={predictionImageSrc}
						onZoom={(src, label) => (zoomImage = { src, label })}
					/>
				{/if}

				<Panel flush>
					<div class="divide-y divide-line">
						{#if diskOtherThumbs.length > 0}
							<Disclosure
								title="Other channels"
								help="{diskOtherThumbs.length} views from C2 and C3"
								bind:open={openChannels}
							>
								{#if openChannels}
									<div class="px-(--pad-panel) pb-2">
										<PieceThumbGrid
											items={diskOtherThumbs}
											minPx={96}
											onZoom={(t) => (zoomImage = { src: t.src, label: t.ref.source })}
										/>
									</div>
								{/if}
							</Disclosure>
						{/if}
						{#if recordFacts.length > 0}
							<Disclosure title="Record" help="Run and recording time">
								<div class="px-(--pad-panel)"><KeyValue items={recordFacts} /></div>
							</Disclosure>
						{/if}
					</div>
				</Panel>
			{:else if _fetchStatus === 'loading' || _fetchStatus === 'idle'}
				<Panel>
					<p class="flex items-center gap-2 text-sm text-ink-muted">
						<Spinner size={16} />
						Loading the piece
					</p>
				</Panel>
			{:else if _fetchStatus === 'not_found'}
				<EmptyState title="No trace of this piece">
					It isn't in backend memory, the durable piece records or the on-disk image store. Go back
					to the
					<a href="/records/pieces" class="text-primary-ink hover:underline">piece records</a>.
				</EmptyState>
			{:else}
				<Alert tone="danger" title="This piece did not load">
					Check the backend connection and try again.
				</Alert>
			{/if}
		{:else}
			<!-- What you came to see: the pictures, what the machine decided, the review. -->
			<PieceOverview
				name={piece.part_name ?? piece.part_id ?? unnamed(piece.classification_status)}
				partId={piece.part_name ? (piece.part_id ?? null) : null}
				frames={overviewFrames}
				framesNote="{overviewFrames.length} frames from C4. Tinted frames produced the result."
				reference={refImageSrc}
				facts={liveFacts}
				summary={_summary}
				endpointBase={effectiveBase()}
				{onReviewed}
				onZoom={(src, label) => (zoomImage = { src, label })}
			/>

			<!-- What went wrong with it, when anything did. -->
			<PieceProblems problems={_summary?.problems} />

			<!-- What each service said about it. -->
			{#if _predictions.length > 0}
				<PiecePredictions
					predictions={_predictions}
					imageSrc={predictionImageSrc}
					onZoom={(src, label) => (zoomImage = { src, label })}
				/>
			{/if}

			<!-- How it got there: closed until asked for, each with what it says. -->
			<Panel flush>
				<div class="divide-y divide-line">
					{#if attempts.length > 0}
						<!-- The parallel Brickognize calls (combined and single-image variants).
						     Each ran concurrently; the highest-confidence "found" call wins and
						     is marked applied. It shows what every request returned, not just the
						     winner, so a confused fused set against a clean lone frame is visible
						     at a glance. -->
						<Disclosure
							title="Classification requests"
							help={requestsHelp}
							bind:open={openRequests}
						>
							{#if openRequests}
								<ul class="divide-y divide-line">
									{#each attempts as a, ai (ai)}
										{@const open = expandedAttempts.has(ai)}
										{@const sent = attemptImages(a)}
										<li class={a.applied ? 'bg-primary-soft' : ''}>
											<button
												type="button"
												aria-expanded={open}
												class="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-(--pad-panel) py-2 text-left text-sm transition-colors hover:bg-hover"
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
													class="num {a.error
														? 'text-danger-ink'
														: a.found
															? 'font-medium text-ink'
															: 'text-ink-muted'}"
												>
													{attemptOutcome(a)}
												</span>
												{#if a.found && a.part_name}<span class="text-ink-muted">{a.part_name}</span
													>{/if}
												{#if a.found && a.color_name}<span class="text-ink-muted"
														>· {a.color_name}</span
													>{/if}
												{#if a.error}<span class="text-ink-muted">{a.error}</span>{/if}
												{#if a.duration_s != null}
													<span class="num text-ink-muted">{a.duration_s.toFixed(2)}s</span>
												{/if}
												{#if a.applied}
													<span
														class="ml-auto"
														title="This request's result was applied to the piece"
													>
														<Badge tone="primary">Applied</Badge>
													</span>
												{/if}
											</button>
											{#if open}
												<div class="flex flex-wrap gap-6 px-(--pad-panel) pb-3">
													<!-- What was sent to Brickognize for this request -->
													<div class="flex flex-col gap-2">
														<div class="label">Sent ({sent.length})</div>
														{#if sent.length === 0}
															<div
																class="flex size-24 items-center justify-center rounded-control bg-well text-sm text-ink-muted"
															>
																Crops aged out
															</div>
														{:else}
															<div class="flex flex-wrap gap-2">
																{#each sent as crop (cropKey(crop))}
																	{@render thumbCrop(
																		crop.src,
																		crop.role,
																		formatCropLabel(crop),
																		() =>
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
															<div
																class="flex size-24 items-center justify-center rounded-control bg-danger-soft p-2 text-center text-sm text-danger-ink"
															>
																{a.error}
															</div>
														{:else if a.found}
															<div class="flex gap-3">
																{#if a.preview_url}
																	{@render thumbCrop(
																		a.preview_url,
																		'Brickognize reference',
																		'',
																		() =>
																			(zoomImage = {
																				src: a.preview_url as string,
																				label: a.part_name ?? a.part_id ?? 'result'
																			})
																	)}
																{/if}
																<div class="flex flex-col gap-0.5 text-sm">
																	<span class="num font-medium text-ink">{a.part_id}</span>
																	{#if a.part_name}<span class="text-ink-muted">{a.part_name}</span
																		>{/if}
																	{#if a.confidence != null}
																		<span class="num text-ink-muted"
																			>{(a.confidence * 100).toFixed(0)}% match</span
																		>
																	{/if}
																	{#if a.color_name}<span class="text-ink-muted"
																			>Color: {a.color_name}</span
																		>{/if}
																</div>
															</div>
														{:else}
															<div
																class="flex size-24 items-center justify-center rounded-control bg-well text-sm text-ink-muted"
															>
																No match
															</div>
														{/if}
													</div>
												</div>
											{/if}
										</li>
									{/each}
								</ul>
							{/if}
						</Disclosure>
					{/if}

					<!-- The same physical piece as seen upstream, ranked by the piece-link
					     model. Tinted tiles were fused into the Brickognize request alongside
					     the burst; the rest are shown for review. -->
					<Disclosure
						title="Other channels"
						help="{otherChannelThumbs.length} views from C2 and C3{linkMatchCount > 0
							? ', ranked by match probability'
							: ''}"
						bind:open={openChannels}
					>
						{#if openChannels}
							<div class="px-(--pad-panel) pb-2">
								{#if otherChannelThumbs.length === 0}
									<p class="text-sm text-ink-muted">No upstream views of this piece.</p>
								{:else}
									<PieceThumbGrid
										items={otherChannelThumbs}
										minPx={96}
										overlay={cropOverlay}
										onZoom={(t) => (zoomImage = { src: t.src, label: formatCropLabel(t.ref) })}
									/>
								{/if}
							</div>
						{/if}
					</Disclosure>

					<!-- Every BrickLink bucket from the Hive catalog. The headline
					     `moving_avg_price` (what routing uses) is the first non-empty of these,
					     sold-new preferred; the table shows all four so you can see whatever
					     source actually exists for this part. -->
					{#if pricing}
						{@const md = pricing}
						{@const price = (md.price ?? null) as Record<string, any> | null}
						{@const bl = (md.bricklink ?? null) as Record<string, any> | null}
						<Disclosure title="Pricing" help={pricingHelp} bind:open={openPricing}>
							{#if openPricing}
								<div class="flex flex-col gap-2 pb-1 text-sm">
									<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-(--pad-panel)">
										<span class="text-ink-muted">
											Moving average, used for routing. From the Hive catalog{md.price_currency
												? `, BrickLink ${md.price_currency}`
												: ''}; first available, sold new preferred.
										</span>
										{#if md.price_updated_at}
											<span class="text-xs text-ink-muted"
												>Synced {String(md.price_updated_at).slice(0, 10)}</span
											>
										{/if}
									</div>
									{#if md.price_from_base_mold}
										<div class="px-(--pad-panel)">
											<Alert tone="warning" title="Approximate">
												There is no market data for this exact print. This shows the base mold
												<span class="font-mono">{md.price_from_base_mold}</span
												>{md.price_from_base_name ? ` (${md.price_from_base_name})` : ''} price instead.
											</Alert>
										</div>
									{/if}
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
										<p class="px-(--pad-panel) text-ink-muted">
											No price-guide rows for this part in the Hive catalog.
										</p>
									{/if}
									{#if bl}
										<div
											class="flex flex-wrap gap-x-4 gap-y-1 px-(--pad-panel) text-xs text-ink-muted"
										>
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
							{/if}
						</Disclosure>
					{/if}

					<Disclosure title="Lifecycle timeline" help={timelineHelp} bind:open={openTimeline}>
						{#if openTimeline}
							<div class="px-(--pad-panel) pb-2">
								{#if timeline.length === 0}
									<p class="text-sm text-ink-muted">No lifecycle events recorded yet.</p>
								{:else}
									{@const anchor = timeline[0].ts}
									<ol class="@container grid gap-x-8 gap-y-0.5 text-sm md:grid-cols-2">
										{#each timeline as ev, idx (idx)}
											<li class="flex items-baseline gap-3">
												<span class="min-w-[11rem] text-ink">{ev.label}</span>
												<span class="num font-mono text-ink-muted">{formatAbsTs(ev.ts)}</span>
												{#if idx > 0}
													<span class="num font-mono text-xs text-ink-muted"
														>{formatRelSec(ev.ts, anchor)}</span
													>
												{/if}
											</li>
										{/each}
									</ol>
								{/if}
							</div>
						{/if}
					</Disclosure>

					{#if recordFacts.length > 0}
						<Disclosure
							title="Record"
							help={recordFacts.map((r) => `${r.label.toLowerCase()} ${r.value}`).join(' · ')}
						>
							<div class="px-(--pad-panel)"><KeyValue items={recordFacts} /></div>
						</Disclosure>
					{/if}

					<!-- Arrival snapshot: the full carousel frame at the instant the piece first
					     appeared on C4 (dropping in from C3). -->
					{#if piece.drop_snapshot}
						{@const drop_src = dataImageUrl(piece.drop_snapshot) as string}
						<Disclosure title="Arrival snapshot" help="The carousel frame as the piece dropped in">
							<div class="px-(--pad-panel)">
								{@render thumbCrop(
									drop_src,
									'arrival snapshot',
									'At arrival',
									() => (zoomImage = { src: drop_src, label: 'At arrival' })
								)}
							</div>
						</Disclosure>
					{/if}

					<!-- Scratch reclassify: pick crops, re-run Brickognize (not recorded) -->
					{#if crops.length > 0}
						<Disclosure
							title="Scratch reclassify"
							help="Pick crops and run Brickognize again; not recorded"
							bind:open={openReclassify}
						>
							{#if openReclassify}
								<div class="px-(--pad-panel) pb-2">
									<ReclassifyPanel
										endpointBase={effectiveBase()}
										images={crops.map((c) => ({
											image: c.src,
											label: formatCropLabel(c),
											used: c.used
										}))}
									/>
								</div>
							{/if}
						</Disclosure>
					{/if}

					<!-- Raw JSON -->
					<Disclosure title="Raw JSON" bind:open={showRawJson}>
						{#if showRawJson}
							<pre
								class="mx-(--pad-panel) max-h-96 overflow-auto rounded-control bg-well p-3 text-xs text-ink-muted">{JSON.stringify(
									piece,
									null,
									2
								)}</pre>
						{/if}
					</Disclosure>
				</div>
			</Panel>
		{/if}
	</div>
</AppShell>

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
{/snippet}

<Modal
	open={zoomImage !== null}
	title={zoomImage?.label ?? 'Image'}
	size="lg"
	onclose={() => (zoomImage = null)}
>
	{#if zoomImage}
		<img
			src={zoomImage.src}
			alt={zoomImage.label}
			class="mx-auto max-h-[70vh] max-w-full object-contain"
		/>
	{/if}
</Modal>
