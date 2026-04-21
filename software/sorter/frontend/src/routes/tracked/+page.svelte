<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { RefreshCw, Trash2 } from 'lucide-svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import AppHeader from '$lib/components/AppHeader.svelte';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import type { KnownObjectData } from '$lib/api/events';
	import { getMachineContext } from '$lib/machines/context';

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
	};

	type FilterMode = 'all' | 'active' | 'distributed' | 'classified' | 'lost';

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	function dataImageUrl(payload: string | null | undefined): string | null {
		return payload ? `data:image/jpeg;base64,${payload}` : null;
	}

	function previewSrc(row: TrackedPieceRow): string | null {
		return (
			dataImageUrl(row.piece.top_image) ??
			dataImageUrl(row.piece.bottom_image) ??
			dataImageUrl(row.piece.thumbnail) ??
			dataImageUrl(row.track_summary?.best_piece_jpeg_b64) ??
			dataImageUrl(row.track_summary?.composite_jpeg_b64)
		);
	}

	function topStrip(row: TrackedPieceRow): string[] {
		return (row.track_summary?.top_piece_jpegs ?? []).slice(0, 4);
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

	function statusLabel(piece: KnownObjectData): string {
		if (piece.classification_channel_zone_state === 'lost' && piece.stage !== 'distributed') {
			return 'Track Lost';
		}
		if (piece.classification_status === 'multi_drop_fail') return 'Multi-drop';
		if (piece.stage === 'distributed') return 'Distributed';
		if (piece.stage === 'distributing') return 'Distributing';
		if (piece.classification_status === 'classified') return 'Classified';
		if (piece.classification_status === 'unknown') return 'Unknown';
		if (piece.classification_status === 'not_found') return 'Not Found';
		if (piece.classification_status === 'classifying') return 'Classifying';
		if (piece.carousel_snapping_started_at || piece.first_carousel_seen_ts) return 'Capturing';
		return 'Tracking';
	}

	function statusClass(piece: KnownObjectData): string {
		if (piece.classification_channel_zone_state === 'lost' && piece.stage !== 'distributed') {
			return 'border-warning bg-warning/10 text-warning-dark';
		}
		if (piece.classification_status === 'multi_drop_fail') {
			return 'border-danger bg-danger/10 text-danger';
		}
		if (piece.stage === 'distributed') return 'border-border bg-surface text-text-muted';
		if (piece.stage === 'distributing') return 'border-primary bg-primary/10 text-primary';
		if (piece.classification_status === 'classified') return 'border-success bg-success/10 text-success';
		if (
			piece.classification_status === 'unknown' ||
			piece.classification_status === 'not_found'
		) {
			return 'border-warning bg-warning/10 text-warning-dark';
		}
		return 'border-border bg-bg text-text-muted';
	}

	function primaryLabel(row: TrackedPieceRow): string {
		const piece = row.piece;
		if (piece.classification_status === 'multi_drop_fail') return 'Multi-drop failure';
		if (piece.classification_status === 'unknown' || piece.classification_status === 'not_found') {
			return 'Unrecognized piece';
		}
		if (piece.part_name) return piece.part_name;
		if (piece.part_id) return piece.part_id;
		if (row.active) return 'Tracked piece in flight';
		return 'Tracked piece';
	}

	function secondaryLabel(row: TrackedPieceRow): string {
		const piece = row.piece;
		const parts: string[] = [];
		if (piece.part_id && piece.part_name) parts.push(piece.part_id);
		if (piece.color_name && piece.color_name !== 'Any Color') parts.push(piece.color_name);
		if (piece.category_id) parts.push(piece.category_id);
		if (parts.length > 0) return parts.join(' · ');
		if (row.track_summary?.roles?.length) return formatRoles(row.track_summary.roles);
		return 'Classification channel dossier';
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

	function syncUrl() {
		if (typeof window === 'undefined') return;
		const params = new URLSearchParams();
		if (limit !== 120) params.set('limit', String(limit));
		if (filter !== 'all') params.set('show', filter);
		const next = params.toString();
		const current = page.url?.search?.replace(/^\?/, '') ?? '';
		if (next === current) return;
		void goto(next ? `?${next}` : '?', { replaceState: true, keepFocus: true, noScroll: true });
	}

	$effect(() => {
		limit;
		filter;
		untrack(syncUrl);
	});

	async function load(): Promise<void> {
		loading = true;
		try {
			const res = await fetch(`${effectiveBase()}/api/tracked/pieces?limit=${limit}`);
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
			const res = await fetch(`${effectiveBase()}/api/feeder/tracking/history`, {
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

	let filteredItems = $derived.by<TrackedPieceRow[]>(() => {
		if (filter === 'all') return items;
		if (filter === 'active') return items.filter((item) => item.active);
		if (filter === 'distributed') return items.filter((item) => item.piece.stage === 'distributed');
		if (filter === 'classified') {
			return items.filter((item) => item.piece.classification_status === 'classified');
		}
		return items.filter(
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
			total: items.length,
			active: 0,
			live: 0,
			classified: 0,
			distributed: 0,
			lost: 0
		};
		for (const item of items) {
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
					class="inline-flex items-center gap-1.5 border border-danger/40 bg-danger/10 px-2 py-1.5 text-xs font-medium text-danger transition-colors hover:bg-danger/20 disabled:cursor-not-allowed disabled:opacity-40"
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
			<div class="border border-border bg-surface px-3 py-2 text-xs text-text-muted">
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
							<p class="mt-1 text-xs text-text-muted">
								Current pieces in flight, ordered along the classification channel path.
							</p>
						</div>
						<span class="tabular-nums text-xs text-text-muted">{activeItems.length} visible</span>
					</div>
					<div class="grid gap-3 xl:grid-cols-2">
						{#each activeItems as row (row.uuid)}
							<a
								href={`/tracked/${row.uuid}`}
								class="grid gap-px border border-border bg-border text-left transition-colors hover:border-primary/70 sm:grid-cols-[176px,1fr]"
							>
								<div class="flex flex-col bg-bg">
									<div class="relative aspect-square bg-black">
										{#if previewSrc(row)}
											<img
												src={previewSrc(row) as string}
												alt="Piece preview"
												class="block h-full w-full object-contain"
												loading="lazy"
											/>
										{:else}
											<div class="flex h-full items-center justify-center px-4 text-center text-xs text-text-muted">
												No image yet
											</div>
										{/if}
										<span class="absolute top-2 left-2 border border-success bg-bg/85 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-success">
											Live
										</span>
										{#if row.tracked_global_id != null}
											<span class="absolute top-2 right-2 border border-border bg-bg/85 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text tabular-nums">
												Track {row.tracked_global_id}
											</span>
										{/if}
									</div>
									{#if topStrip(row).length > 0}
										<div class="grid grid-cols-4 gap-px bg-border">
											{#each topStrip(row) as crop, idx (`${row.uuid}-${idx}`)}
												<div class="aspect-square bg-bg">
													<img
														src={`data:image/jpeg;base64,${crop}`}
														alt="Tracked crop"
														class="block h-full w-full object-contain"
														loading="lazy"
													/>
												</div>
											{/each}
										</div>
									{/if}
								</div>
								<div class="flex flex-col gap-3 bg-surface px-4 py-3">
									<div class="flex flex-wrap items-start justify-between gap-2">
										<div class="min-w-0">
											<div class="text-base font-semibold text-text">{primaryLabel(row)}</div>
											<div class="mt-0.5 text-sm text-text-muted">{secondaryLabel(row)}</div>
										</div>
										<span class={`inline-flex items-center border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider ${statusClass(row.piece)}`}>
											{statusLabel(row.piece)}
										</span>
									</div>

									<div class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Path</span>
											<span class="text-text">{formatRoles(row.track_summary?.roles)}</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Drop offset</span>
											<span class="tabular-nums text-text">
												{row.polar_offset_deg != null ? `${row.polar_offset_deg.toFixed(1)}°` : '—'}
											</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Crops</span>
											<span class="tabular-nums text-text">
												{row.track_summary?.max_sector_snapshots ?? 0}
											</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Last update</span>
											<span class="tabular-nums text-text">
												{formatRelativeTime(row.piece.updated_at)}
											</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Duration</span>
											<span class="tabular-nums text-text">
												{formatDuration(row.track_summary?.duration_s)}
											</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Handoffs</span>
											<span class="tabular-nums text-text">
												{row.track_summary?.handoff_count ?? 0}
											</span>
										</div>
									</div>

									{#if recognitionLine(row)}
										<div class="border-t border-border pt-2 text-sm text-text-muted">
											<span class="font-medium text-text">Recognition</span>
											<span class="ml-2">{recognitionLine(row)}</span>
										</div>
									{/if}
								</div>
							</a>
						{/each}
					</div>
				</section>
			{/if}

			{#if historyItems.length > 0}
				<section class="flex flex-col gap-3">
					<div class="flex items-end justify-between gap-3 border-b border-border pb-2">
						<div>
							<h3 class="text-sm font-semibold uppercase tracking-wider text-text">Session History</h3>
							<p class="mt-1 text-xs text-text-muted">
								Persistent dossiers from this sorting session, newest confirmed activity first.
							</p>
						</div>
						<span class="tabular-nums text-xs text-text-muted">{historyItems.length} visible</span>
					</div>
					<div class="grid gap-3 xl:grid-cols-2">
						{#each historyItems as row (row.uuid)}
							<a
								href={`/tracked/${row.uuid}`}
								class="grid gap-px border border-border bg-border text-left transition-colors hover:border-primary/70 sm:grid-cols-[176px,1fr]"
							>
								<div class="flex flex-col bg-bg">
									<div class="relative aspect-square bg-black">
										{#if previewSrc(row)}
											<img
												src={previewSrc(row) as string}
												alt="Piece preview"
												class="block h-full w-full object-contain"
												loading="lazy"
											/>
										{:else}
											<div class="flex h-full items-center justify-center px-4 text-center text-xs text-text-muted">
												No stored preview
											</div>
										{/if}
										<span class={`absolute top-2 left-2 inline-flex border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${statusClass(row.piece)}`}>
											{statusLabel(row.piece)}
										</span>
										{#if row.tracked_global_id != null}
											<span class="absolute top-2 right-2 border border-border bg-bg/85 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text tabular-nums">
												Track {row.tracked_global_id}
											</span>
										{/if}
									</div>
									{#if topStrip(row).length > 0}
										<div class="grid grid-cols-4 gap-px bg-border">
											{#each topStrip(row) as crop, idx (`${row.uuid}-history-${idx}`)}
												<div class="aspect-square bg-bg">
													<img
														src={`data:image/jpeg;base64,${crop}`}
														alt="Tracked crop"
														class="block h-full w-full object-contain"
														loading="lazy"
													/>
												</div>
											{/each}
										</div>
									{/if}
								</div>
								<div class="flex flex-col gap-3 bg-surface px-4 py-3">
									<div class="flex flex-wrap items-start justify-between gap-2">
										<div class="min-w-0">
											<div class="text-base font-semibold text-text">{primaryLabel(row)}</div>
											<div class="mt-0.5 text-sm text-text-muted">{secondaryLabel(row)}</div>
										</div>
										{#if row.piece.confidence != null}
											<span class="tabular-nums text-sm text-text-muted">
												{(row.piece.confidence * 100).toFixed(0)}%
											</span>
										{/if}
									</div>

									<div class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Path</span>
											<span class="text-text">{formatRoles(row.track_summary?.roles)}</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Bin</span>
											<span class="tabular-nums text-text">{formatBin(row.piece.destination_bin)}</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Finished</span>
											<span class="tabular-nums text-text">
												{formatRelativeTime(
													(row.piece.distributed_at as number | null | undefined) ??
														(row.history_finished_at as number | null | undefined) ??
														row.piece.updated_at
												)}
											</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Duration</span>
											<span class="tabular-nums text-text">
												{formatDuration(row.track_summary?.duration_s)}
											</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Segments</span>
											<span class="tabular-nums text-text">
												{row.track_summary?.segment_count ?? 0}
											</span>
										</div>
										<div class="flex flex-col">
											<span class="text-[11px] uppercase tracking-wider text-text-muted">Hits</span>
											<span class="tabular-nums text-text">
												{row.track_summary?.total_hit_count ?? 0}
											</span>
										</div>
									</div>

									{#if recognitionLine(row)}
										<div class="border-t border-border pt-2 text-sm text-text-muted">
											<span class="font-medium text-text">Recognition</span>
											<span class="ml-2">{recognitionLine(row)}</span>
										</div>
									{/if}
								</div>
							</a>
						{/each}
					</div>
				</section>
			{/if}
		{/if}
	</div>
</div>
