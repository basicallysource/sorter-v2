<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { RefreshCw, Trash2 } from 'lucide-svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { KnownObjectData } from '$lib/api/events';
	import { getMachineContext } from '$lib/machines/context';
	import { sortingProfileStore } from '$lib/stores/sortingProfile.svelte';
	import { LEGO_COLORS, type LegoColor } from '$lib/lego-colors';
	import {
		capturedCropUrl,
		lifecyclePhase,
		pieceCropUrl,
		type LifecyclePhase
	} from '$lib/recent-pieces';
	import { formatTrackLabel } from '$lib/trackLabel';

	type AutoRecognition = {
		status: 'pending' | 'ok' | 'insufficient_consistency' | 'insufficient_quality' | 'error';
		image_count?: number;
		total_crops?: number;
		inlier_count?: number;
		queued_count?: number;
		kept_count?: number;
		rejected_for_quality?: number;
		error?: string;
		best_item?: { id: string; name: string; score: number; img_url?: string } | null;
		best_color?: { id: string; name: string } | null;
	};

	type TrackSummary = {
		roles?: string[];
		handoff_count?: number;
		segment_count?: number;
		total_hit_count?: number;
		max_sector_snapshots?: number;
		composite_jpeg_b64?: string;
		best_piece_jpeg_b64?: string;
		top_piece_jpegs?: string[];
		auto_recognition?: AutoRecognition | null;
		finished_at?: number;
		duration_s?: number;
		live?: boolean;
	};

	type TrackedPieceRow = {
		uuid: string;
		piece: KnownObjectData;
		tracked_global_id?: number | null;
		global_id?: number | null;
		live: boolean;
		active: boolean;
		polar_angle_deg?: number | null;
		polar_offset_deg?: number | null;
		track_summary?: TrackSummary | null;
		sort_ts: number;
		history_finished_at?: number | null;
		has_track_segments?: boolean;
		preview_jpeg_path?: string | null;
	};

	type FilterMode = 'all' | 'active' | 'distributed' | 'classified' | 'lost';

	const ctx = getMachineContext();

	onMount(() => {
		void sortingProfileStore.load().catch(() => {});
	});

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	function dataImageUrl(payload: string | null | undefined): string | null {
		return payload ? `data:image/jpeg;base64,${payload}` : null;
	}

	function capturedFor(row: TrackedPieceRow): string | null {
		return (
			capturedCropUrl(row.piece) ??
			dataImageUrl(row.track_summary?.best_piece_jpeg_b64) ??
			dataImageUrl(row.track_summary?.composite_jpeg_b64) ??
			pieceCropUrl(row.preview_jpeg_path, effectiveBase())
		);
	}

	function referenceFor(row: TrackedPieceRow): string | null {
		return row.piece.brickognize_preview_url ?? null;
	}

	function formatRelativeTime(ts: number | null | undefined): string {
		if (!ts) return '—';
		const diff = Math.max(0, Date.now() / 1000 - ts);
		if (diff < 60) return `${Math.round(diff)}s ago`;
		if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
		return `${Math.round(diff / 3600)}h ago`;
	}

	function formatDuration(seconds: number | null | undefined): string {
		if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return '—';
		if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		const mins = Math.floor(seconds / 60);
		return `${mins}m ${Math.floor(seconds % 60)}s`;
	}

	function formatBin(bin: [unknown, unknown, unknown] | null | undefined): string {
		if (!bin) return '—';
		return `L${bin[0]} · S${bin[1]} · B${bin[2]}`;
	}

	function formatRoles(roles: string[] | undefined): string {
		if (!roles || roles.length === 0) return '—';
		return roles
			.map((role) => {
				if (role === 'carousel') return 'C4';
				if (role === 'c_channel_3') return 'C3';
				if (role === 'c_channel_2') return 'C2';
				return role;
			})
			.join(' → ');
	}

	function formatSyncPercent(ratio: number | null | undefined): string {
		if (typeof ratio !== 'number' || !Number.isFinite(ratio)) return '—';
		return `${(ratio * 100).toFixed(0)}%`;
	}

	function motionSyncRatio(piece: KnownObjectData): number | null {
		if (typeof piece.carousel_motion_sync_ratio_avg === 'number') {
			return piece.carousel_motion_sync_ratio_avg;
		}
		if (typeof piece.carousel_motion_sync_ratio === 'number') {
			return piece.carousel_motion_sync_ratio;
		}
		return null;
	}

	function motionSyncClass(piece: KnownObjectData): string {
		const ratio = motionSyncRatio(piece);
		if (ratio == null) return 'text-text-muted';
		if (ratio < 0.5) return 'text-danger';
		if (ratio < 0.85 || ratio > 1.15) return 'text-warning-dark';
		return 'text-success';
	}

	const PHASE_LABEL: Record<LifecyclePhase, string> = {
		tracking: 'Tracking',
		capturing: 'Capturing',
		classified: 'Classified',
		distributed: 'Distributed'
	};

	function phaseChipClass(phase: LifecyclePhase): string {
		if (phase === 'tracking') return 'border-text-muted bg-text-muted/10 text-text-muted';
		if (phase === 'capturing') return 'border-primary bg-primary/10 text-primary';
		if (phase === 'classified') return 'border-success bg-success/10 text-success';
		return 'border-border bg-surface text-text-muted';
	}

	function statusOverrideChip(piece: KnownObjectData): { label: string; cls: string } | null {
		if (piece.classification_channel_zone_state === 'lost' && piece.stage !== 'distributed') {
			return {
				label: 'Track Lost',
				cls: 'border-warning bg-warning/10 text-warning-dark'
			};
		}
		if (piece.classification_status === 'multi_drop_fail') {
			return { label: 'Multi-drop', cls: 'border-danger bg-danger/10 text-danger' };
		}
		if (piece.classification_status === 'unknown' || piece.classification_status === 'not_found') {
			return {
				label: piece.classification_status === 'not_found' ? 'Not Found' : 'Unknown',
				cls: 'border-warning bg-warning/10 text-warning-dark'
			};
		}
		return null;
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

	function confidenceClass(conf: number): string {
		const pct = conf * 100;
		if (pct >= 90) return 'text-success';
		if (pct >= 80) return 'text-warning';
		if (pct >= 60) return 'text-warning/70';
		return 'text-danger';
	}

	function primaryLabel(row: TrackedPieceRow): string {
		const piece = row.piece;
		if (piece.classification_status === 'multi_drop_fail') return 'Multi drop — rejected';
		if (piece.classification_status === 'not_found') return 'Not recognized by Brickognize';
		if (piece.classification_status === 'unknown') return 'Unknown piece';
		if (piece.part_name) return piece.part_name;
		if (piece.part_id) return piece.part_id;
		if (row.active) return 'Tracked piece in flight';
		return 'Tracked piece';
	}

	function primaryClass(piece: KnownObjectData): string {
		if (piece.classification_status === 'multi_drop_fail') return 'text-danger';
		if (piece.classification_status === 'unknown' || piece.classification_status === 'not_found') {
			return 'text-text-muted';
		}
		return 'text-text';
	}

	function recognitionLine(row: TrackedPieceRow): string | null {
		const rec = row.track_summary?.auto_recognition;
		if (rec?.status === 'ok' && rec.best_item) {
			return `${rec.best_item.id} · ${(rec.best_item.score * 100).toFixed(0)}%`;
		}
		if (rec?.status === 'pending') {
			return `Recognizing${rec.queued_count ? ` · ${rec.queued_count} crops queued` : '…'}`;
		}
		if (rec?.status === 'insufficient_consistency') {
			return `Mixed crops${rec.inlier_count && rec.total_crops ? ` · ${rec.inlier_count}/${rec.total_crops}` : ''}`;
		}
		if (rec?.status === 'insufficient_quality') {
			return `Low quality${rec.kept_count && rec.total_crops ? ` · ${rec.kept_count}/${rec.total_crops}` : ''}`;
		}
		if (rec?.status === 'error') return 'Recognition failed';
		return null;
	}

	let items = $state<TrackedPieceRow[]>([]);
	let loading = $state(false);
	let clearing = $state(false);
	let dropAngleDeg = $state<number | null>(null);

	const initialParams =
		typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
	let limit = $state(Number(initialParams?.get('limit') ?? 120));
	let filter = $state<FilterMode>((initialParams?.get('show') as FilterMode) ?? 'all');
	let showStubs = $state(initialParams?.get('stubs') === '1');
	let search = $state(initialParams?.get('q') ?? '');

	function syncUrl() {
		if (typeof window === 'undefined') return;
		const params = new URLSearchParams();
		if (limit !== 120) params.set('limit', String(limit));
		if (filter !== 'all') params.set('show', filter);
		if (showStubs) params.set('stubs', '1');
		if (search.trim()) params.set('q', search.trim());
		const next = params.toString();
		const current = page.url?.search?.replace(/^\?/, '') ?? '';
		if (next === current) return;
		void goto(next ? `?${next}` : '?', { replaceState: true, keepFocus: true, noScroll: true });
	}

	$effect(() => {
		limit;
		filter;
		showStubs;
		search;
		untrack(syncUrl);
	});

	async function load(): Promise<void> {
		loading = true;
		try {
			const query = new URLSearchParams({ limit: String(limit) });
			if (showStubs) query.set('include_stubs', 'true');
			const res = await fetch(`${effectiveBase()}/api/tracked/pieces?${query.toString()}`);
			if (!res.ok) return;
			const json = await res.json();
			items = Array.isArray(json?.items) ? (json.items as TrackedPieceRow[]) : [];
			dropAngleDeg =
				typeof json?.drop_angle_deg === 'number' ? (json.drop_angle_deg as number) : null;
		} catch {
			// ignore
		} finally {
			loading = false;
		}
	}

	async function clearAll(): Promise<void> {
		if (clearing) return;
		if (
			!window.confirm(
				'Delete all tracked pieces? This wipes the persisted dossier history and the tracker archive for this session.'
			)
		) {
			return;
		}
		clearing = true;
		try {
			const res = await fetch(`${effectiveBase()}/api/tracked/pieces`, {
				method: 'DELETE'
			});
			if (!res.ok) return;
			items = [];
		} catch {
			// ignore
		} finally {
			clearing = false;
			void load();
		}
	}

	onMount(() => {
		void load();
		const id = setInterval(() => void load(), 2000);
		return () => clearInterval(id);
	});

	// Refresh relative timestamps every second.
	let now_tick = $state(0);
	$effect(() => {
		const id = setInterval(() => (now_tick += 1), 1000);
		return () => clearInterval(id);
	});
	$effect(() => {
		void now_tick;
	});

	// Phase 6 dedupe: keep rows keyed by uuid (primary) or tracked_global_id
	// (fallback). Rows without either cannot be navigated to and are dropped.
	// In practice the backend guarantees uuid after Phase 4 — this is a
	// defensive filter, not an expected code path.
	function rowKey(row: TrackedPieceRow): string | null {
		if (row.uuid) return `uuid:${row.uuid}`;
		if (row.tracked_global_id !== null && row.tracked_global_id !== undefined) {
			return `gid:${row.tracked_global_id}`;
		}
		return null;
	}

	let dedupedItems = $derived.by<TrackedPieceRow[]>(() => {
		const seen = new Set<string>();
		const out: TrackedPieceRow[] = [];
		for (const row of items) {
			const key = rowKey(row);
			if (key === null) continue;
			if (seen.has(key)) continue;
			seen.add(key);
			out.push(row);
		}
		return out;
	});

	// Defense-in-depth against ghost-stub dossiers. The backend's
	// ``include_stubs=False`` query already filters the main zombie cases;
	// this mirror keeps the UI defensive but must match backend semantics:
	// anything the rt runtime has promoted past "created" (confirmed_real,
	// stage registered/classified/distributed) is a real piece, not a stub.
	function isGhostStub(row: TrackedPieceRow): boolean {
		if (row.has_track_segments === true) return false;
		const piece = row.piece as KnownObjectData & {
			confirmed_real?: boolean;
		};
		if (piece.confirmed_real === true) return false;
		const stage = piece.stage as string | undefined;
		if (stage && stage !== 'created') return false;
		return piece.classification_status === 'pending';
	}

	let visibleItems = $derived.by<TrackedPieceRow[]>(() => {
		if (showStubs) return dedupedItems;
		return dedupedItems.filter((item) => !isGhostStub(item));
	});

	function matchesSearch(row: TrackedPieceRow, needle: string): boolean {
		if (!needle) return true;
		const haystacks: (string | number | null | undefined)[] = [
			formatTrackLabel(row.tracked_global_id),
			row.tracked_global_id,
			row.uuid,
			row.piece.part_id,
			row.piece.part_name,
			row.piece.color_name,
			row.piece.color_id
		];
		for (const value of haystacks) {
			if (value == null) continue;
			if (String(value).toLowerCase().includes(needle)) return true;
		}
		return false;
	}

	let filteredItems = $derived.by<TrackedPieceRow[]>(() => {
		const needle = search.trim().toLowerCase();
		const bySearch = needle
			? visibleItems.filter((item) => matchesSearch(item, needle))
			: visibleItems;
		if (filter === 'all') return bySearch;
		if (filter === 'active') return bySearch.filter((item) => item.active);
		if (filter === 'distributed') {
			return bySearch.filter((item) => item.piece.stage === 'distributed');
		}
		if (filter === 'classified') {
			return bySearch.filter((item) => item.piece.classification_status === 'classified');
		}
		return bySearch.filter(
			(item) =>
				item.piece.classification_channel_zone_state === 'lost' &&
				item.piece.stage !== 'distributed'
		);
	});

	let activeItems = $derived(filteredItems.filter((item) => item.active));
	let historyItems = $derived(filteredItems.filter((item) => !item.active));

	type Stats = {
		total: number;
		active: number;
		live: number;
		classified: number;
		distributed: number;
		lost: number;
	};

	let stats = $derived.by<Stats>(() => {
		const next: Stats = {
			total: dedupedItems.length,
			active: 0,
			live: 0,
			classified: 0,
			distributed: 0,
			lost: 0
		};
		for (const item of dedupedItems) {
			if (item.active) next.active++;
			if (item.live) next.live++;
			if (item.piece.classification_status === 'classified') next.classified++;
			if (item.piece.stage === 'distributed') next.distributed++;
			if (
				item.piece.classification_channel_zone_state === 'lost' &&
				item.piece.stage !== 'distributed'
			) {
				next.lost++;
			}
		}
		return next;
	});
</script>

{#snippet pieceRow(row: TrackedPieceRow)}
	{@const piece = row.piece}
	{@const phase = lifecyclePhase(piece)}
	{@const captured = capturedFor(row)}
	{@const reference = referenceFor(row)}
	{@const is_unknown =
		piece.classification_status === 'unknown' || piece.classification_status === 'not_found'}
	{@const is_multi_drop = piece.classification_status === 'multi_drop_fail'}
	{@const is_classified_ok = !is_unknown && !is_multi_drop && Boolean(reference)}
	{@const cat_name = piece.category_id ? sortingProfileStore.getCategoryName(piece.category_id) : null}
	{@const lego_color =
		!is_unknown && !is_multi_drop && piece.color_name && piece.color_name !== 'Any Color'
			? lookupLegoColor(piece.color_id, piece.color_name)
			: null}
	{@const status_override = statusOverrideChip(piece)}
	{@const rec_line = recognitionLine(row)}
	{@const finished_ts =
		(piece.distributed_at as number | null | undefined) ??
		(row.history_finished_at as number | null | undefined) ??
		piece.classified_at ??
		piece.updated_at}

	<a
		href={`/tracked/${row.uuid}`}
		class="block border border-border bg-bg transition-colors hover:border-primary/70"
	>
		<div class="flex items-stretch gap-3 p-3">
			<div class="group relative h-32 w-32 flex-shrink-0 border border-border bg-white">
				{#if is_classified_ok && captured}
					<img
						src={reference}
						alt="Reference"
						class="absolute inset-0 h-full w-full object-contain transition-opacity duration-150 group-hover:opacity-0"
					/>
					<img
						src={captured}
						alt="Captured"
						class="absolute inset-0 h-full w-full object-contain opacity-0 transition-opacity duration-150 group-hover:opacity-100"
					/>
				{:else if is_classified_ok && !captured}
					<img src={reference} alt="Reference" class="h-full w-full object-contain" />
				{:else if captured}
					<img src={captured} alt="Captured" class="h-full w-full object-contain" />
				{:else}
					<div class="flex h-full w-full items-center justify-center">
						<Spinner />
					</div>
				{/if}
				{#if row.live}
					<span class="absolute top-1 left-1 border border-success bg-bg/90 px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-success">
						Live
					</span>
				{/if}
				{#if row.tracked_global_id != null}
					{@const trackLabel = formatTrackLabel(row.tracked_global_id)}
					{#if trackLabel}
						<span class="absolute bottom-1 right-1 border border-border bg-bg/90 px-1.5 py-0.5 font-mono text-xs text-text tabular-nums">
							#{trackLabel}
						</span>
					{/if}
				{/if}
				{#if phase === 'capturing' || phase === 'tracking'}
					<div class="absolute -top-1 -right-1">
						<Spinner />
					</div>
				{/if}
			</div>

			<div class="flex min-w-0 flex-1 flex-col gap-2">
				<div class="flex items-baseline justify-between gap-3">
					<span class="truncate text-base font-semibold {primaryClass(piece)}">
						{primaryLabel(row)}
					</span>
					{#if typeof piece.confidence === 'number' && !is_unknown && !is_multi_drop}
						<span class="flex-shrink-0 text-base font-semibold tabular-nums {confidenceClass(piece.confidence)}">
							{(piece.confidence * 100).toFixed(0)}%
						</span>
					{/if}
				</div>

				{#if piece.part_name && piece.part_id}
					<div class="truncate font-mono text-sm text-text-muted">{piece.part_id}</div>
				{:else if phase === 'tracking' && !is_unknown && !is_multi_drop}
					<div class="text-sm text-text-muted">Tracked on carousel…</div>
				{:else if phase === 'capturing' && !is_unknown && !is_multi_drop}
					<div class="text-sm text-text-muted">Capturing on C4…</div>
				{/if}

				<div class="flex flex-wrap items-center gap-1.5">
					{#if status_override}
						<span class="inline-flex items-center border px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider {status_override.cls}">
							{status_override.label}
						</span>
					{:else}
						<span class="inline-flex items-center border px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider {phaseChipClass(phase)}">
							{PHASE_LABEL[phase]}
						</span>
					{/if}

					{#if lego_color}
						<span
							class="inline-flex items-center border border-border px-1.5 py-0.5 text-xs font-semibold"
							style:background-color={lego_color.hex}
							style:color={lego_color.contrast === 'white' ? '#ffffff' : '#000000'}
						>
							{lego_color.name}
						</span>
					{:else if piece.color_name && piece.color_name !== 'Any Color' && !is_unknown && !is_multi_drop}
						<span class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs text-text-muted">
							{piece.color_name}
						</span>
					{/if}

					{#if cat_name && !is_unknown && !is_multi_drop}
						<span class="text-xs text-text-muted">{cat_name}</span>
					{/if}

					{#if row.has_track_segments}
						<span
							class="inline-flex items-center border border-border bg-surface px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wider text-text-muted"
							title="Persisted segment dossier available"
						>
							Segments
						</span>
					{/if}

					{#if piece.destination_bin && phase === 'distributed'}
						<span class="ml-auto inline-flex items-center border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text tabular-nums">
							{is_unknown || is_multi_drop ? 'discard ' : ''}{formatBin(piece.destination_bin)}
						</span>
					{:else if phase === 'distributed' && (is_unknown || is_multi_drop)}
						<span class="ml-auto inline-flex items-center border border-border bg-surface px-1.5 py-0.5 font-mono text-xs text-text-muted">
							discard bin
						</span>
					{/if}
				</div>

				<div class="mt-auto grid grid-cols-2 gap-x-4 gap-y-1 border-t border-border pt-2 text-sm sm:grid-cols-3 lg:grid-cols-4">
					<div class="flex items-baseline justify-between gap-2">
						<span class="text-xs uppercase tracking-wider text-text-muted">Path</span>
						<span class="text-sm text-text">{formatRoles(row.track_summary?.roles)}</span>
					</div>
					{#if row.active}
						<div class="flex items-baseline justify-between gap-2">
							<span class="text-xs uppercase tracking-wider text-text-muted">Drop Δ</span>
							<span class="tabular-nums text-sm text-text">
								{row.polar_offset_deg != null ? `${row.polar_offset_deg.toFixed(1)}°` : '—'}
							</span>
						</div>
					{:else}
						<div class="flex items-baseline justify-between gap-2">
							<span class="text-xs uppercase tracking-wider text-text-muted">Bin</span>
							<span class="tabular-nums text-sm text-text">{formatBin(piece.destination_bin)}</span>
						</div>
					{/if}
					<div class="flex items-baseline justify-between gap-2">
						<span class="text-xs uppercase tracking-wider text-text-muted">Duration</span>
						<span class="tabular-nums text-sm text-text">{formatDuration(row.track_summary?.duration_s)}</span>
					</div>
					<div class="flex items-baseline justify-between gap-2">
						<span class="text-xs uppercase tracking-wider text-text-muted">
							{row.active ? 'Updated' : 'Finished'}
						</span>
						<span class="tabular-nums text-sm text-text">
							{formatRelativeTime(row.active ? piece.updated_at : finished_ts)}
						</span>
					</div>
					<div class="flex items-baseline justify-between gap-2">
						<span class="text-xs uppercase tracking-wider text-text-muted">Crops</span>
						<span class="tabular-nums text-sm text-text">{row.track_summary?.max_sector_snapshots ?? 0}</span>
					</div>
					<div class="flex items-baseline justify-between gap-2">
						<span class="text-xs uppercase tracking-wider text-text-muted">Handoffs</span>
						<span class="tabular-nums text-sm text-text">{row.track_summary?.handoff_count ?? 0}</span>
					</div>
					<div class="flex items-baseline justify-between gap-2">
						<span class="text-xs uppercase tracking-wider text-text-muted">Hits</span>
						<span class="tabular-nums text-sm text-text">{row.track_summary?.total_hit_count ?? 0}</span>
					</div>
					<div class="flex items-baseline justify-between gap-2">
						<span class="text-xs uppercase tracking-wider text-text-muted">Sync</span>
						<span class="tabular-nums text-sm {motionSyncClass(piece)}">
							{formatSyncPercent(motionSyncRatio(piece))}
						</span>
					</div>
				</div>

				{#if rec_line}
					<div class="text-sm text-text-muted">
						<span class="font-medium text-text">Recognition</span>
						<span class="ml-2">{rec_line}</span>
					</div>
				{/if}
			</div>
		</div>
	</a>
{/snippet}

<svelte:head>
	<title>Tracked Pieces · Sorter</title>
</svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="flex flex-col gap-5 p-4 sm:p-6">
		<header class="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
			<div class="max-w-3xl">
				<h2 class="text-xl font-bold text-text">Tracked Pieces</h2>
				<p class="mt-1 text-sm text-text-muted">
					Session-persistent piece dossiers: lifecycle, tracking path, crops, burst shots and
					distribution outcome in one place.
				</p>
			</div>
			<div class="flex flex-wrap items-center gap-3 text-sm text-text-muted">
				<label class="flex items-center gap-2">
					<span>limit</span>
					<input
						type="number"
						min="20"
						max="500"
						step="20"
						bind:value={limit}
						onchange={() => void load()}
						class="w-20 border border-border bg-bg px-2 py-1 text-text tabular-nums"
					/>
				</label>
				<label class="flex items-center gap-2">
					<span>show</span>
					<select
						bind:value={filter}
						class="border border-border bg-bg px-2 py-1 text-sm text-text"
					>
						<option value="all">all</option>
						<option value="active">active</option>
						<option value="distributed">distributed</option>
						<option value="classified">classified</option>
						<option value="lost">track lost</option>
					</select>
				</label>
				<label class="flex items-center gap-2">
					<span>search</span>
					<input
						type="search"
						bind:value={search}
						placeholder="0007, part id, color…"
						class="w-44 border border-border bg-bg px-2 py-1 text-sm text-text placeholder:text-text-muted"
					/>
				</label>
				<label
					class="flex items-center gap-1.5 text-sm text-text-muted"
					title="Debug: include pending ghost-stub dossiers (no track segments yet)"
				>
					<input
						type="checkbox"
						bind:checked={showStubs}
						onchange={() => void load()}
						class="h-3.5 w-3.5 border border-border bg-bg"
					/>
					<span>stubs</span>
				</label>
				<button
					type="button"
					onclick={() => void load()}
					disabled={loading}
					aria-label="Reload tracked pieces"
					title="Reload tracked pieces"
					class="border border-border bg-surface p-1.5 text-text-muted transition-colors hover:text-text disabled:opacity-50"
				>
					<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
				</button>
				<button
					type="button"
					onclick={() => void clearAll()}
					disabled={clearing || items.length === 0}
					class="inline-flex items-center gap-1.5 border border-danger/40 bg-danger/10 px-2 py-1.5 text-sm font-medium text-danger transition-colors hover:bg-danger/20 disabled:cursor-not-allowed disabled:opacity-40"
				>
					<Trash2 size={14} />
					<span>{clearing ? 'Clearing…' : 'Clear all'}</span>
				</button>
			</div>
		</header>

		<div class="grid grid-cols-2 gap-px border border-border bg-border text-sm sm:grid-cols-3 xl:grid-cols-6">
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Pieces</span>
				<span class="tabular-nums text-base font-semibold text-text">{stats.total}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Active</span>
				<span class="tabular-nums text-base font-semibold text-primary">{stats.active}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Live</span>
				<span class="tabular-nums text-base font-semibold text-success-dark">{stats.live}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Classified</span>
				<span class="tabular-nums text-base font-semibold text-success-dark">{stats.classified}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Distributed</span>
				<span class="tabular-nums text-base font-semibold text-text">{stats.distributed}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Track lost</span>
				<span class="tabular-nums text-base font-semibold text-warning-dark">{stats.lost}</span>
			</div>
		</div>

		{#if dropAngleDeg != null}
			<div class="border border-border bg-surface px-3 py-2 text-sm text-text-muted">
				Active pieces are ordered by polar offset to the C4 drop angle
				<span class="tabular-nums text-text">({dropAngleDeg.toFixed(1)}°)</span>, not by arrival time.
			</div>
		{/if}

		{#if filteredItems.length === 0}
			<div class="flex min-h-40 items-center justify-center border border-dashed border-border bg-surface text-sm text-text-muted">
				{items.length === 0 ? 'No tracked pieces yet.' : 'No pieces match the current filter.'}
			</div>
		{:else}
			{#if activeItems.length > 0}
				<section class="flex flex-col gap-3">
					<div class="flex items-end justify-between gap-3 border-b border-border pb-2">
						<div>
							<h3 class="text-sm font-semibold uppercase tracking-wider text-text">On Ring</h3>
							<p class="mt-1 text-sm text-text-muted">
								Current pieces in flight, ordered along the classification channel path.
							</p>
						</div>
						<span class="tabular-nums text-sm text-text-muted">{activeItems.length} visible</span>
					</div>
					<div class="grid gap-2 xl:grid-cols-2">
						{#each activeItems as row (rowKey(row) ?? row.uuid)}
							{@render pieceRow(row)}
						{/each}
					</div>
				</section>
			{/if}

			{#if historyItems.length > 0}
				<section class="flex flex-col gap-3">
					<div class="flex items-end justify-between gap-3 border-b border-border pb-2">
						<div>
							<h3 class="text-sm font-semibold uppercase tracking-wider text-text">Session History</h3>
							<p class="mt-1 text-sm text-text-muted">
								Persistent dossiers from this sorting session, newest confirmed activity first.
							</p>
						</div>
						<span class="tabular-nums text-sm text-text-muted">{historyItems.length} visible</span>
					</div>
					<div class="grid gap-2 xl:grid-cols-2">
						{#each historyItems as row (rowKey(row) ?? row.uuid)}
							{@render pieceRow(row)}
						{/each}
					</div>
				</section>
			{/if}
		{/if}
	</div>
</div>
