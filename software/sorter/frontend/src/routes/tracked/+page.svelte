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
	type SortKey = 'ring' | 'updated' | 'name' | 'conf' | 'bin' | 'stage';
	type SortDir = 'asc' | 'desc';

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
			capturedCropUrl(row.piece, effectiveBase()) ??
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

	function formatBin(bin: [unknown, unknown, unknown] | null | undefined): string {
		if (!bin) return '—';
		return `L${bin[0]} · S${bin[1]} · B${bin[2]}`;
	}

	function binLabel(piece: KnownObjectData): string {
		return piece.destination_bin ? formatBin(piece.destination_bin) : (piece.bin_id ?? '—');
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
	let sortKey = $state<SortKey>((initialParams?.get('sort') as SortKey) ?? 'ring');
	let sortDir = $state<SortDir>((initialParams?.get('dir') as SortDir) ?? 'desc');

	function syncUrl() {
		if (typeof window === 'undefined') return;
		const params = new URLSearchParams();
		if (limit !== 120) params.set('limit', String(limit));
		if (filter !== 'all') params.set('show', filter);
		if (showStubs) params.set('stubs', '1');
		if (search.trim()) params.set('q', search.trim());
		if (sortKey !== 'ring') params.set('sort', sortKey);
		if (sortDir !== 'desc') params.set('dir', sortDir);
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
		sortKey;
		sortDir;
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

	// Defense-in-depth: the backend already collapses split dossiers, but the
	// physical identity is still tracked_global_id-first. Keep active and
	// historical rows separate so a completed piece does not hide a live one if
	// the tracker id is reused after a restart.
	function rowKey(row: TrackedPieceRow): string | null {
		if (row.tracked_global_id !== null && row.tracked_global_id !== undefined) {
			const state = row.active ? 'active' : 'history';
			return `gid:${state}:${row.tracked_global_id}`;
		}
		if (row.uuid) return `uuid:${row.uuid}`;
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

	// --- Sorting ----------------------------------------------------------
	// ``ring`` preserves the backend's ordering (active → polar offset;
	// history → most-recent finished). Every other sort key collapses both
	// groups into one flat list sorted by that key/direction.

	function rowFinishedTs(row: TrackedPieceRow): number {
		const piece = row.piece;
		return (
			(piece.distributed_at as number | null | undefined) ??
			(row.history_finished_at as number | null | undefined) ??
			piece.classified_at ??
			piece.updated_at ??
			0
		);
	}

	function binSortKey(piece: KnownObjectData): number {
		const bin = piece.destination_bin;
		if (!bin) return Number.POSITIVE_INFINITY;
		const [l, s, b] = bin;
		return (Number(l) || 0) * 10000 + (Number(s) || 0) * 100 + (Number(b) || 0);
	}

	const STAGE_ORDER: Record<string, number> = {
		created: 0,
		registered: 1,
		classifying: 2,
		classified: 3,
		distributing: 4,
		distributed: 5
	};

	function stageSortKey(piece: KnownObjectData): number {
		const stage = String(piece.stage ?? '');
		return STAGE_ORDER[stage] ?? 99;
	}

	function sortFactor(dir: SortDir): 1 | -1 {
		return dir === 'asc' ? 1 : -1;
	}

	let sortedItems = $derived.by<TrackedPieceRow[]>(() => {
		const list = [...filteredItems];
		if (sortKey === 'ring') {
			// Preserve server order: active (polar offset) followed by history.
			return list.sort((a, b) => (a.active === b.active ? 0 : a.active ? -1 : 1));
		}
		const f = sortFactor(sortDir);
		if (sortKey === 'updated') {
			return list.sort(
				(a, b) => (rowFinishedTs(b) - rowFinishedTs(a)) * (sortDir === 'desc' ? 1 : -1)
			);
		}
		if (sortKey === 'name') {
			return list.sort((a, b) => primaryLabel(a).localeCompare(primaryLabel(b)) * f);
		}
		if (sortKey === 'conf') {
			return list.sort((a, b) => {
				const av = typeof a.piece.confidence === 'number' ? a.piece.confidence : -1;
				const bv = typeof b.piece.confidence === 'number' ? b.piece.confidence : -1;
				return (av - bv) * f;
			});
		}
		if (sortKey === 'bin') {
			return list.sort((a, b) => (binSortKey(a.piece) - binSortKey(b.piece)) * f);
		}
		if (sortKey === 'stage') {
			return list.sort((a, b) => (stageSortKey(a.piece) - stageSortKey(b.piece)) * f);
		}
		return list;
	});

	function cycleSort(key: SortKey): void {
		if (sortKey !== key) {
			sortKey = key;
			sortDir = key === 'name' || key === 'bin' || key === 'stage' ? 'asc' : 'desc';
			return;
		}
		sortDir = sortDir === 'asc' ? 'desc' : 'asc';
	}

	function sortArrow(key: SortKey): string {
		if (sortKey !== key) return '';
		return sortDir === 'asc' ? ' ↑' : ' ↓';
	}

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
	{@const thumb_src = is_classified_ok ? reference : (captured ?? reference)}
	{@const cat_name = piece.category_id ? sortingProfileStore.getCategoryName(piece.category_id) : null}
	{@const category_label = cat_name ?? piece.part_category ?? piece.category_id ?? null}
	{@const bin_label = binLabel(piece)}
	{@const lego_color =
		!is_unknown && !is_multi_drop && piece.color_name && piece.color_name !== 'Any Color'
			? lookupLegoColor(piece.color_id, piece.color_name)
			: null}
	{@const status_override = statusOverrideChip(piece)}
	{@const finished_ts =
		(piece.distributed_at as number | null | undefined) ??
		(row.history_finished_at as number | null | undefined) ??
		piece.classified_at ??
		piece.updated_at}
	{@const age_ts = row.active ? piece.updated_at : finished_ts}
	{@const track_label = row.tracked_global_id != null ? formatTrackLabel(row.tracked_global_id) : null}

	<a
		href={`/tracked/${row.uuid}`}
		class="piece-grid-row grid items-center gap-3 border-b border-border bg-bg px-3 py-1.5 text-sm transition-colors hover:bg-surface"
	>
		<!-- Thumbnail -->
		<div class="relative h-12 w-12 flex-shrink-0 border border-border bg-white">
			{#if thumb_src}
				<img src={thumb_src} alt="" class="h-full w-full object-contain" loading="lazy" />
			{:else}
				<div class="flex h-full w-full items-center justify-center">
					<Spinner />
				</div>
			{/if}
			{#if row.live}
				<span class="absolute -top-1 -right-1 h-2 w-2 bg-success" title="Live"></span>
			{/if}
		</div>

		<!-- Identity: name + part_id + track# -->
		<div class="flex min-w-0 flex-col">
			<span class="truncate font-medium {primaryClass(piece)}">{primaryLabel(row)}</span>
			<span class="truncate font-mono text-xs text-text-muted tabular-nums">
				{piece.part_id ?? '—'}{#if track_label}
					<span class="ml-2">#{track_label}</span>
				{/if}
			</span>
		</div>

		<!-- Color -->
		<div class="flex min-w-0 items-center gap-1.5">
			{#if lego_color}
				<span class="inline-block h-3 w-3 flex-shrink-0 border border-border" style:background-color={lego_color.hex}></span>
				<span class="truncate text-xs text-text">{lego_color.name}</span>
			{:else if piece.color_name && piece.color_name !== 'Any Color' && !is_unknown && !is_multi_drop}
				<span class="truncate text-xs text-text-muted">{piece.color_name}</span>
			{:else}
				<span class="text-xs text-text-muted">—</span>
			{/if}
		</div>

		<!-- Category -->
		<div class="min-w-0">
			{#if category_label && !is_unknown && !is_multi_drop}
				<span class="truncate text-xs text-text-muted">{category_label}</span>
			{:else}
				<span class="text-xs text-text-muted">—</span>
			{/if}
		</div>

		<!-- Confidence -->
		<div class="text-right">
			{#if typeof piece.confidence === 'number' && !is_unknown && !is_multi_drop}
				<span class="font-mono text-xs font-semibold tabular-nums {confidenceClass(piece.confidence)}">
					{(piece.confidence * 100).toFixed(0)}%
				</span>
			{:else}
				<span class="text-xs text-text-muted">—</span>
			{/if}
		</div>

		<!-- Bin / Drop -->
		<div class="text-right">
			{#if phase === 'distributed'}
				<span class="font-mono text-xs tabular-nums {is_unknown || is_multi_drop ? 'text-warning-dark' : 'text-text'}">
					{is_unknown || is_multi_drop ? 'discard' : bin_label}
				</span>
			{:else if row.active && row.polar_offset_deg != null}
				<span class="font-mono text-xs text-text-muted tabular-nums" title="Polar offset to C4 drop angle">
					Δ{row.polar_offset_deg.toFixed(1)}°
				</span>
			{:else if bin_label !== '—'}
				<span class="font-mono text-xs text-text-muted tabular-nums">{bin_label}</span>
			{:else}
				<span class="text-xs text-text-muted">—</span>
			{/if}
		</div>

		<!-- Stage chip -->
		<div>
			{#if status_override}
				<span class="inline-flex items-center border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider {status_override.cls}">
					{status_override.label}
				</span>
			{:else}
				<span class="inline-flex items-center border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider {phaseChipClass(phase)}">
					{PHASE_LABEL[phase]}
				</span>
			{/if}
		</div>

		<!-- Age -->
		<div class="text-right font-mono text-xs text-text-muted tabular-nums">
			{formatRelativeTime(age_ts)}
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
					<span>sort</span>
					<select
						bind:value={sortKey}
						class="border border-border bg-bg px-2 py-1 text-sm text-text"
					>
						<option value="ring">ring position</option>
						<option value="updated">most recent</option>
						<option value="name">name</option>
						<option value="conf">confidence</option>
						<option value="bin">bin</option>
						<option value="stage">stage</option>
					</select>
					{#if sortKey !== 'ring'}
						<button
							type="button"
							onclick={() => (sortDir = sortDir === 'asc' ? 'desc' : 'asc')}
							title={sortDir === 'asc' ? 'Ascending' : 'Descending'}
							class="border border-border bg-bg px-2 py-1 font-mono text-sm text-text"
						>
							{sortDir === 'asc' ? '↑' : '↓'}
						</button>
					{/if}
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

		{#if sortKey === 'ring' && dropAngleDeg != null && stats.active > 0}
			<div class="border border-border bg-surface px-3 py-1.5 text-xs text-text-muted">
				Ring order: active pieces first, ordered by polar offset to the C4 drop angle
				<span class="tabular-nums text-text">({dropAngleDeg.toFixed(1)}°)</span>.
			</div>
		{/if}

		{#if sortedItems.length === 0}
			<div class="flex min-h-40 items-center justify-center border border-dashed border-border bg-surface text-sm text-text-muted">
				{items.length === 0 ? 'No tracked pieces yet.' : 'No pieces match the current filter.'}
			</div>
		{:else}
			<div class="border border-border bg-surface">
				<!-- Header row: sortable column labels -->
				<div class="piece-grid-row grid items-center gap-3 border-b border-border bg-bg px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
					<div></div>
					<button type="button" class="flex items-center text-left hover:text-text" onclick={() => cycleSort('name')}>
						Piece{sortArrow('name')}
					</button>
					<div>Color</div>
					<div>Category</div>
					<button type="button" class="text-right hover:text-text" onclick={() => cycleSort('conf')}>
						Conf{sortArrow('conf')}
					</button>
					<button type="button" class="text-right hover:text-text" onclick={() => cycleSort('bin')}>
						Bin / Δ{sortArrow('bin')}
					</button>
					<button type="button" class="text-left hover:text-text" onclick={() => cycleSort('stage')}>
						Stage{sortArrow('stage')}
					</button>
					<button type="button" class="text-right hover:text-text" onclick={() => cycleSort('updated')}>
						Age{sortArrow('updated')}
					</button>
				</div>

				{#each sortedItems as row (rowKey(row) ?? row.uuid)}
					{@render pieceRow(row)}
				{/each}
			</div>

			<div class="text-xs text-text-muted tabular-nums">
				{sortedItems.length} piece{sortedItems.length === 1 ? '' : 's'} shown
			</div>
		{/if}
	</div>
</div>

<style>
	/* Piece list: one grid template for header + rows so columns align.
	   Collapses to a 2-column (thumb + identity) block on narrow viewports. */
	.piece-grid-row {
		grid-template-columns: 48px 1fr;
	}

	@media (min-width: 900px) {
		.piece-grid-row {
			grid-template-columns:
				48px
				minmax(0, 1.4fr)
				minmax(0, 0.9fr)
				minmax(0, 0.9fr)
				56px
				80px
				90px
				64px;
		}
	}
</style>
