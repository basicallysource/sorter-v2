<script lang="ts">
	import { onMount, untrack } from 'svelte';
	import { RefreshCw, HelpCircle, CircleSlash, Trash2 } from 'lucide-svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { backendHttpBaseUrl, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import AppHeader from '$lib/components/AppHeader.svelte';
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

	type HistoryItem = {
		global_id: number;
		created_at: number;
		finished_at: number;
		duration_s: number;
		roles: string[];
		handoff_count: number;
		segment_count: number;
		total_hit_count: number;
		live: boolean;
		composite_jpeg_b64?: string;
		best_piece_jpeg_b64?: string;
		top_piece_jpegs?: string[];
		max_sector_snapshots?: number;
		auto_recognition?: AutoRecognition | null;
	};

	function hasRecognitionAttempt(item: HistoryItem): boolean {
		return item.auto_recognition != null;
	}

	const ctx = getMachineContext();

	function effectiveBase(): string {
		return machineHttpBaseUrlFromWsUrl(ctx.machine?.url) ?? backendHttpBaseUrl;
	}

	// Per-row link resolution: the tracker-history feed (HistoryItem) is the
	// authoritative list source — it has persistent records, composites,
	// recognition stats — but it does not carry the KnownObject UUID the
	// lifecycle detail page is keyed by. For rows whose piece is still in
	// the live `recentObjects` ring (most recent ~10), we resolve the UUID
	// and link directly to the lifecycle detail. Older rows fall back to
	// /tracked/${global_id}, which the [uuid] route accepts but renders
	// with the "not in live buffer" fallback. Once the backend exposes a
	// global_id → uuid lookup (or a full KnownObject history endpoint) the
	// fallback branch can be removed.
	function detailHrefFor(global_id: number): string {
		const recent = ctx.machine?.recentObjects ?? [];
		const match = recent.find((o) => o.tracked_global_id === global_id);
		return match ? `/tracked/${match.uuid}` : `/tracked/${global_id}`;
	}

	let items = $state<HistoryItem[]>([]);

	// Seed filter state from URL so reload / back-button preserves what the
	// user was looking at. Pushing updates back to the URL happens in a
	// dedicated effect below.
	const initialParams =
		typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
	let minSectors = $state(Number(initialParams?.get('min') ?? 3));
	let limit = $state(Number(initialParams?.get('limit') ?? 120));
	let loading = $state(false);
	let viewMode = $state<'large' | 'compact'>(
		(initialParams?.get('view') as 'large' | 'compact') ?? 'compact'
	);
	let filter = $state<'all' | 'attempted' | 'recognized'>(
		(initialParams?.get('show') as 'all' | 'attempted' | 'recognized') ?? 'all'
	);

	function syncUrl() {
		if (typeof window === 'undefined') return;
		const params = new URLSearchParams();
		if (minSectors !== 3) params.set('min', String(minSectors));
		if (limit !== 120) params.set('limit', String(limit));
		if (viewMode !== 'compact') params.set('view', viewMode);
		if (filter !== 'all') params.set('show', filter);
		const search = params.toString();
		const current = page.url?.search?.replace(/^\?/, '') ?? '';
		if (search === current) return;
		void goto(`?${search}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	$effect(() => {
		minSectors;
		limit;
		viewMode;
		filter;
		untrack(syncUrl);
	});

	let filteredItems = $derived.by<HistoryItem[]>(() => {
		if (filter === 'all') return items;
		if (filter === 'attempted') {
			return items.filter((it) => it.auto_recognition != null);
		}
		// recognized
		return items.filter((it) => it.auto_recognition?.status === 'ok');
	});

	type Stats = {
		total: number;
		attempted: number;
		recognized: number;
		mixed: number;
		lowQuality: number;
		failed: number;
		avgSectors: number;
		live: number;
	};

	let stats = $derived.by<Stats>(() => {
		const s: Stats = {
			total: items.length,
			attempted: 0,
			recognized: 0,
			mixed: 0,
			lowQuality: 0,
			failed: 0,
			avgSectors: 0,
			live: 0
		};
		let sectorSum = 0;
		let sectorCount = 0;
		for (const it of items) {
			if (it.live) s.live++;
			if (it.max_sector_snapshots != null) {
				sectorSum += it.max_sector_snapshots;
				sectorCount++;
			}
			const st = it.auto_recognition?.status;
			if (st != null) s.attempted++;
			if (st === 'ok') s.recognized++;
			else if (st === 'insufficient_consistency') s.mixed++;
			else if (st === 'insufficient_quality') s.lowQuality++;
			else if (st === 'error') s.failed++;
		}
		s.avgSectors = sectorCount > 0 ? sectorSum / sectorCount : 0;
		return s;
	});

	async function load() {
		loading = true;
		try {
			const res = await fetch(
				`${effectiveBase()}/api/feeder/tracking/history?limit=${limit}&min_sectors=${minSectors}`
			);
			if (!res.ok) return;
			const json = await res.json();
			const raw: HistoryItem[] = Array.isArray(json?.items) ? json.items : [];
			// c_channel_2 is too noisy on its own, but in the classification-
			// channel setup we also want to surface pieces that are currently
			// or historically visible on the Classification Channel itself.
			items = raw.filter(
				(it) =>
					Array.isArray(it.roles) &&
					it.roles.some((role) => role === 'c_channel_3' || role === 'carousel')
			);
		} catch {
			// ignore
		} finally {
			loading = false;
		}
	}

	function formatHashId(id: number): string {
		const mixed = (id * 2654435761) >>> 0;
		return (mixed % 10000).toString().padStart(4, '0');
	}

	function formatDuration(seconds: number): string {
		if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
		if (seconds < 60) return `${seconds.toFixed(1)}s`;
		const m = Math.floor(seconds / 60);
		return `${m}m ${Math.floor(seconds % 60)}s`;
	}

	function formatRole(role: string): string {
		if (role === 'carousel') return 'Classification Channel';
		if (role === 'c_channel_2') return 'C2';
		if (role === 'c_channel_3') return 'C3';
		return role.replace('c_channel_', 'C');
	}

	function formatRoles(roles: string[]): string {
		return roles.map((role) => formatRole(role)).join(' → ');
	}

	onMount(() => {
		void load();
	});

	// Filter changes trigger an explicit fetch — no $effect, because
	// capturing reactive context reads (e.g. ctx.machine.url heartbeats)
	// would silently re-trigger the load on every websocket event.
	function onFilterChange() {
		void load();
	}

	let clearing = $state(false);

	async function clearAll() {
		if (clearing) return;
		if (
			!window.confirm(
				'Delete all tracked pieces? This wipes the persisted history on disk and cannot be undone.'
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
</script>

<svelte:head>
	<title>Tracked Pieces · Sorter</title>
</svelte:head>

<div class="min-h-screen bg-bg">
	<AppHeader />
	<div class="flex flex-col gap-4 p-4 sm:p-6">
		<header class="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-3">
			<div>
				<h2 class="text-xl font-bold text-text">Tracked Pieces</h2>
				<p class="mt-1 text-sm text-text-muted">
					Each card is a piece the tracker followed across the feeder ring. Click to open the full trajectory.
				</p>
			</div>
		<div class="flex flex-wrap items-center gap-4 text-sm text-text-muted">
			<label class="flex items-center gap-2">
				<span>min sectors</span>
				<input
					type="number"
					min="0"
					max="12"
					bind:value={minSectors}
					onchange={onFilterChange}
					class="w-16 border border-border bg-bg px-2 py-1 text-text"
				/>
			</label>
			<label class="flex items-center gap-2">
				<span>limit</span>
				<input
					type="number"
					min="10"
					max="300"
					step="10"
					bind:value={limit}
					onchange={onFilterChange}
					class="w-20 border border-border bg-bg px-2 py-1 text-text"
				/>
			</label>
			<label class="flex items-center gap-2">
				<span>show</span>
				<select
					bind:value={filter}
					class="border border-border bg-bg px-2 py-1 text-sm text-text"
				>
					<option value="all">all</option>
					<option value="attempted">attempted</option>
					<option value="recognized">recognized</option>
				</select>
			</label>
			<div class="flex border border-border">
				<button
					type="button"
					onclick={() => (viewMode = 'compact')}
					class={`border-r border-border px-2 py-1 text-sm ${viewMode === 'compact' ? 'bg-primary/20 text-primary' : 'bg-surface text-text-muted hover:text-text'}`}
				>
					Compact
				</button>
				<button
					type="button"
					onclick={() => (viewMode = 'large')}
					class={`px-2 py-1 text-sm ${viewMode === 'large' ? 'bg-primary/20 text-primary' : 'bg-surface text-text-muted hover:text-text'}`}
				>
					Large
				</button>
			</div>
			<span class="text-text-muted">{filteredItems.length} shown</span>
			<button
				type="button"
				onclick={() => void load()}
				disabled={loading}
				aria-label="Reload"
				title="Reload tracked pieces"
				class="border border-border bg-surface p-1.5 text-text-muted hover:text-text disabled:opacity-50"
			>
				<RefreshCw size={14} class={loading ? 'animate-spin' : ''} />
			</button>
			<button
				type="button"
				onclick={() => void clearAll()}
				disabled={clearing || items.length === 0}
				aria-label="Clear all tracked pieces"
				title="Clear all tracked pieces"
				class="inline-flex items-center gap-1.5 border border-danger/40 bg-danger/10 px-2 py-1.5 text-xs font-medium text-danger hover:bg-danger/20 disabled:cursor-not-allowed disabled:opacity-40"
			>
				<Trash2 size={14} />
				<span>{clearing ? 'Clearing…' : 'Clear all'}</span>
			</button>
		</div>
	</header>

	{#if stats.total > 0}
		<div class="grid grid-cols-2 gap-px border border-border bg-border text-sm sm:grid-cols-4 lg:grid-cols-7">
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Tracks</span>
				<span class="font-mono text-base font-semibold text-text">{stats.total}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Live</span>
				<span class="font-mono text-base font-semibold text-text">{stats.live}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Attempted</span>
				<span class="font-mono text-base font-semibold text-text">{stats.attempted}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Recognized</span>
				<span class="font-mono text-base font-semibold text-success-dark">{stats.recognized}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Mixed</span>
				<span class="font-mono text-base font-semibold text-warning-dark">{stats.mixed}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Low quality</span>
				<span class="font-mono text-base font-semibold text-warning-dark">{stats.lowQuality}</span>
			</div>
			<div class="flex flex-col bg-surface px-3 py-2">
				<span class="text-xs uppercase tracking-wider text-text-muted">Avg crops</span>
				<span class="font-mono text-base font-semibold text-text">{stats.avgSectors.toFixed(1)}</span>
			</div>
		</div>
	{/if}

	{#if filteredItems.length === 0}
		<div class="flex min-h-40 items-center justify-center border border-dashed border-border bg-surface text-sm text-text-muted">
			{items.length === 0 ? 'No pieces tracked yet.' : 'No pieces match the current filter.'}
		</div>
	{:else if viewMode === 'compact'}
		<div class="grid gap-3" style="grid-template-columns: repeat(auto-fill, minmax(440px, 1fr));">
			{#each filteredItems as item (item.global_id)}
				{@const crops = item.top_piece_jpegs ?? []}
				{@const showRecognitionGrid = hasRecognitionAttempt(item)}
				<a
					href={detailHrefFor(item.global_id)}
					class="flex flex-col border border-border bg-surface text-left transition-colors hover:border-primary/70"
				>
					{#if showRecognitionGrid}
						<!-- After a recognition attempt, switch to the 3x3 view:
						     Brickognize match in the middle, up to 8 crops around it. -->
						<div class="relative grid grid-cols-3 gap-px bg-border">
							{#each Array(9) as _, cellIdx (cellIdx)}
								{#if cellIdx === 4}
									{@const auto = item.auto_recognition}
									{@const hasMatch = auto?.status === 'ok' && !!auto.best_item?.img_url}
									{@const notChecked = auto == null || auto.status === 'pending'}
									<div
										class="relative z-10 flex aspect-square items-center justify-center border-4 border-primary bg-white shadow-[0_0_0_2px_rgba(255,255,255,0.95)]"
									>
										{#if hasMatch}
											<img
												src={auto!.best_item!.img_url}
												alt="Brickognize match"
												class="block h-full w-full object-contain"
												loading="lazy"
											/>
										{:else if notChecked}
											<HelpCircle size={72} class="text-text-muted" strokeWidth={1.5} />
										{:else}
											<CircleSlash size={72} class="text-warning-dark" strokeWidth={1.5} />
										{/if}
									</div>
								{:else}
									{@const cropIdx = cellIdx < 4 ? cellIdx : cellIdx - 1}
									{@const cropB64 = crops[cropIdx]}
									<div class="flex aspect-square items-center justify-center bg-bg">
										{#if cropB64}
											<img
												src={`data:image/jpeg;base64,${cropB64}`}
												alt="Piece crop"
												class="block h-full w-full object-contain"
												loading="lazy"
											/>
										{:else}
											<span class="text-xs text-text-muted">·</span>
										{/if}
									</div>
								{/if}
							{/each}
							<span
								class={`absolute top-1.5 left-1.5 z-10 inline-flex h-2 w-2 rounded-full ${
									item.live ? 'bg-success' : 'bg-text-muted/70'
								}`}
								aria-hidden="true"
							></span>
							{#if item.handoff_count > 0}
								<span class="absolute top-1.5 right-1.5 z-10 border border-primary bg-bg/80 px-1 text-xs font-medium text-primary">
									H
								</span>
							{/if}
						</div>
					{:else}
						<div class="relative aspect-square w-full bg-black">
							{#if item.composite_jpeg_b64}
								<img
									src={`data:image/jpeg;base64,${item.composite_jpeg_b64}`}
									alt="Tracked piece composite"
									class="block h-full w-full object-cover"
									loading="lazy"
								/>
							{:else if item.best_piece_jpeg_b64}
								<img
									src={`data:image/jpeg;base64,${item.best_piece_jpeg_b64}`}
									alt="Tracked piece crop"
									class="block h-full w-full object-contain bg-white"
									loading="lazy"
								/>
							{:else}
								<div class="flex h-full w-full items-center justify-center text-xs text-text-muted">
									{item.live ? 'Tracking…' : '—'}
								</div>
							{/if}
							<span
								class={`absolute top-1.5 left-1.5 z-10 inline-flex h-2 w-2 rounded-full ${
									item.live ? 'bg-success' : 'bg-text-muted/70'
								}`}
								aria-hidden="true"
							></span>
							{#if item.handoff_count > 0}
								<span class="absolute top-1.5 right-1.5 z-10 border border-primary bg-bg/80 px-1 text-xs font-medium text-primary">
									H
								</span>
							{/if}
							<div class="absolute inset-x-0 bottom-0 bg-black/60 px-2 py-1 text-xs text-white">
								trajectory composite
							</div>
						</div>
					{/if}
					<div class="flex flex-col gap-0.5 px-2.5 py-2 text-sm">
						<div class="flex items-center justify-between">
							<span class="font-mono font-semibold text-text">#{formatHashId(item.global_id)}</span>
							<span class="text-text-muted">{formatDuration(item.duration_s)}</span>
						</div>
						{#if item.auto_recognition?.status === 'ok' && item.auto_recognition.best_item}
							<span class="font-mono font-medium text-text">
								{item.auto_recognition.best_item.id} · {(item.auto_recognition.best_item.score * 100).toFixed(0)}%
							</span>
							<span class="truncate text-text-muted" title={item.auto_recognition.best_item.name}>
								{item.auto_recognition.best_item.name}
							</span>
						{:else if item.auto_recognition?.status === 'pending'}
							<span class="text-text-muted">Recognizing…</span>
						{:else if item.auto_recognition?.status === 'insufficient_consistency'}
							<span class="text-warning-dark">Mixed crops</span>
						{:else if item.auto_recognition?.status === 'insufficient_quality'}
							<span class="text-warning-dark">Low quality</span>
						{:else if item.auto_recognition?.status === 'error'}
							<span class="text-danger">Recognize failed</span>
						{:else}
							<span class="text-text-muted">{formatRoles(item.roles)}</span>
						{/if}
					</div>
				</a>
			{/each}
		</div>
	{:else}
		<div class="grid gap-4" style="grid-template-columns: repeat(auto-fill, minmax(660px, 1fr));">
			{#each filteredItems as item (item.global_id)}
				<a
					href={detailHrefFor(item.global_id)}
					class="group flex flex-col border border-border bg-surface text-left transition-colors hover:border-primary/70"
				>
					<div class="relative aspect-square w-full bg-black">
						{#if item.composite_jpeg_b64}
							<img
								src={`data:image/jpeg;base64,${item.composite_jpeg_b64}`}
								alt=""
								class="block h-full w-full object-cover"
							/>
						{:else}
							<div class="flex h-full w-full items-center justify-center text-sm text-text-muted">
								{item.live ? '…' : '—'}
							</div>
						{/if}
						<span
							class={`absolute top-2 left-2 inline-flex h-2 w-2 rounded-full ${
								item.live ? 'bg-success' : 'bg-text-muted/70'
							}`}
							aria-hidden="true"
						></span>
						{#if item.handoff_count > 0}
							<span class="absolute top-2 right-2 border border-primary bg-bg/80 px-1.5 py-0.5 text-xs font-medium text-primary">
								handoff
							</span>
						{/if}
						{#if item.live}
							<span class="absolute bottom-2 left-2 border border-success bg-bg/80 px-1.5 py-0.5 text-xs font-medium text-success">
								LIVE
							</span>
						{/if}
					</div>
					<div class="flex flex-col gap-1 px-3 py-2 text-sm text-text">
						<div class="flex items-center justify-between">
							<span class="font-mono text-sm font-semibold">#{formatHashId(item.global_id)}</span>
							<span class="text-text-muted">{formatDuration(item.duration_s)}</span>
						</div>
						<div class="flex items-center justify-between text-text-muted">
							<span>{formatRoles(item.roles)}</span>
							{#if item.max_sector_snapshots != null}
								<span>{item.max_sector_snapshots} sec.</span>
							{/if}
						</div>
						{#if item.auto_recognition}
							{@const rec = item.auto_recognition}
							<div class="mt-1 flex items-start gap-2 border-t border-border pt-2">
								{#if rec.status === 'ok' && rec.best_item}
									{#if rec.best_item.img_url}
										<img
											src={rec.best_item.img_url}
											alt=""
											class="h-10 w-10 flex-shrink-0 border border-border bg-white object-contain"
											loading="lazy"
										/>
									{/if}
									<div class="flex min-w-0 flex-1 flex-col">
										<span class="font-mono font-medium text-text">
											{rec.best_item.id} · {(rec.best_item.score * 100).toFixed(0)}%
										</span>
										<span class="truncate text-text-muted" title={rec.best_item.name}>
											{rec.best_item.name}
										</span>
										{#if rec.best_color}
											<span class="text-text-muted">{rec.best_color.name}</span>
										{/if}
									</div>
								{:else if rec.status === 'pending'}
									<span class="text-text-muted">Recognizing… ({rec.queued_count ?? ''} crops)</span>
								{:else if rec.status === 'insufficient_consistency'}
									<span class="text-warning-dark" title="Crops don't look like one piece — skipped Brickognize">
										Mixed crops ({rec.inlier_count}/{rec.total_crops})
									</span>
								{:else if rec.status === 'insufficient_quality'}
									<span class="text-warning-dark" title="Too many crops were blurry / overexposed">
										Low quality ({rec.kept_count}/{rec.total_crops})
									</span>
								{:else if rec.status === 'error'}
									<span class="text-danger" title={rec.error}>Recognize failed</span>
								{:else}
									<span class="text-text-muted">No match</span>
								{/if}
							</div>
						{/if}
					</div>
				</a>
			{/each}
		</div>
	{/if}
	</div>
</div>
