<script lang="ts">
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import {
		api,
		type ColorLabelPieceCard,
		type ColorLabelSort,
		type ColorLabelStats,
		type Machine
	} from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import * as nav from '$lib/colorLabelNav';
	import FilterGroup from '$lib/components/FilterGroup.svelte';
	import PaletteCoverage from '$lib/components/PaletteCoverage.svelte';
	import PieceCard from '$lib/components/PieceCard.svelte';
	import PieceLabelPanel, { type PieceLabelPatch } from '$lib/components/PieceLabelPanel.svelte';
	import PieceRow from '$lib/components/PieceRow.svelte';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';
	import ArrowRight from 'lucide-svelte/icons/arrow-right';
	import LayoutGrid from 'lucide-svelte/icons/layout-grid';
	import Rows3 from 'lucide-svelte/icons/rows-3';

	const BATCH = 60;

	const SORTS: { value: ColorLabelSort; label: string }[] = [
		{ value: 'priority', label: 'Priority (candidates, least-labeled)' },
		{ value: 'rare_color', label: 'Likely rare color (low-confidence, near a rare color)' },
		{ value: 'needs_me', label: 'Needs my label' },
		{ value: 'least_color', label: 'Fewest color labels' },
		{ value: 'most_color', label: 'Most color labels' },
		{ value: 'least_crop', label: 'Fewest same-piece labels' },
		{ value: 'most_crop', label: 'Most same-piece labels' },
		{ value: 'recent', label: 'Newest' },
		{ value: 'oldest', label: 'Oldest' }
	];

	type ViewMode = 'grid' | 'rows';

	// Filters initialize from the URL so a shared/back-navigated link restores
	// the same list. Defaults: priority sort, all machines, has-candidates only.
	const initialFilters = nav.filtersFromSearch(page.url.searchParams);
	const initialView: ViewMode = page.url.searchParams.get('view') === 'rows' ? 'rows' : 'grid';
	const initialPiece = parsePieceParam(page.url.searchParams);

	let stats = $state<ColorLabelStats | null>(null);
	let machines = $state<Machine[]>([]);
	let sort = $state<ColorLabelSort>(initialFilters.sort);
	let machineId = $state<string | null>(initialFilters.machineId ?? null);
	// Default: only feed pieces that actually have a same-piece candidate list.
	let withCandidates = $state(initialFilters.withCandidates !== false);
	let view = $state<ViewMode>(initialView);
	let items = $state<ColorLabelPieceCard[]>([]);
	let hasMore = $state(true);
	let offset = 0;
	// Guards against duplicate keys — offset paging over a shifting/ties-heavy
	// order can re-return a piece, which would crash the keyed {#each}.
	let seenKeys = new Set<string>();

	// The piece open in the right-hand labeling pane (a key, so a shared URL can
	// open a piece that isn't in the current list yet).
	let selectedKey = $state<nav.PieceKey | null>(initialPiece);
	const paneOpen = $derived(selectedKey != null);

	function cardKey(c: nav.PieceKey): string {
		return `${c.machine_id}|${c.piece_uuid}`;
	}
	function rowElId(c: nav.PieceKey): string {
		return `pb-${c.machine_id}-${c.piece_uuid}`;
	}
	function sameKey(a: nav.PieceKey, b: nav.PieceKey): boolean {
		return a.machine_id === b.machine_id && a.piece_uuid === b.piece_uuid;
	}

	let loading = $state(true);
	let fetchingMore = $state(false);
	let error = $state<string | null>(null);
	let sentinel = $state<HTMLElement | null>(null);

	const coverage = $derived.by(() => {
		if (!stats || stats.total_labelable === 0) return 0;
		return Math.round((stats.color_labeled_pieces / stats.total_labelable) * 100);
	});
	const hist = $derived(stats?.labeler_histogram ?? { '0': 0, '1': 0, '2': 0, '3+': 0 });
	const histTotal = $derived(Math.max(1, stats?.total_labelable ?? 1));

	const sortLabel = $derived(SORTS.find((s) => s.value === sort)?.label ?? sort);
	const machineName = $derived(machines.find((m) => m.id === machineId)?.name ?? null);

	// Index of the open piece within the current list (-1 if not present).
	const selectedIndex = $derived.by(() => {
		if (!selectedKey) return -1;
		return items.findIndex((c) => sameKey(c, selectedKey!));
	});
	const panePosition = $derived({ index: selectedIndex, total: items.length, hasMore });

	// Machines grouped by owner (matches the Samples machine filter layout).
	const machineGroups = $derived.by(() => {
		const groups = new Map<string, Machine[]>();
		for (const m of machines) {
			const owner = m.owner?.display_name ?? 'Other machines';
			if (!groups.has(owner)) groups.set(owner, []);
			groups.get(owner)!.push(m);
		}
		return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]));
	});

	function errMsg(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e
			? String((e as { error: unknown }).error)
			: fallback;
	}

	function parsePieceParam(sp: URLSearchParams): nav.PieceKey | null {
		const pm = sp.get('pm');
		const pu = sp.get('pu');
		return pm && pu ? { machine_id: pm, piece_uuid: pu } : null;
	}

	function currentFilters(): nav.NavFilters {
		return { sort, machineId, withCandidates };
	}

	// Mirror filters + view + open piece into the URL (replace, not push — these
	// aren't history entries) so a shared/back-navigated link restores the view.
	function syncUrl() {
		const params = new URLSearchParams(nav.filtersToSearch(currentFilters()));
		if (view === 'rows') params.set('view', 'rows');
		if (selectedKey) {
			params.set('pm', selectedKey.machine_id);
			params.set('pu', selectedKey.piece_uuid);
		}
		const qs = params.toString();
		replaceState(`/piece-bboxes${qs ? `?${qs}` : ''}`, {});
	}

	async function loadAll() {
		loading = true;
		error = null;
		items = [];
		seenKeys = new Set();
		offset = 0;
		hasMore = true;
		try {
			const [s, res] = await Promise.all([
				api.colorLabelStats({ machineId }),
				api.colorLabelPieces({ sort, machineId, withCandidates, limit: BATCH, offset: 0 })
			]);
			stats = s;
			offset = res.items.length;
			hasMore = res.has_more;
			for (const c of res.items) {
				if (!seenKeys.has(cardKey(c))) {
					seenKeys.add(cardKey(c));
					items.push(c);
				}
			}
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load dashboard');
		} finally {
			loading = false;
		}
	}

	async function fetchMore() {
		if (fetchingMore || !hasMore || loading) return;
		fetchingMore = true;
		try {
			const res = await api.colorLabelPieces({
				sort,
				machineId,
				withCandidates,
				limit: BATCH,
				offset
			});
			offset += res.items.length;
			hasMore = res.has_more;
			const fresh = res.items.filter((c) => !seenKeys.has(cardKey(c)));
			for (const c of fresh) seenKeys.add(cardKey(c));
			items = [...items, ...fresh];
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load more pieces');
		} finally {
			fetchingMore = false;
		}
	}

	function setSort(next: ColorLabelSort) {
		if (next === sort) return;
		sort = next;
		syncUrl();
		void loadAll();
	}
	function setMachine(next: string | null) {
		if (next === machineId) return;
		machineId = next;
		syncUrl();
		void loadAll();
	}
	function setWithCandidates(next: boolean) {
		if (next === withCandidates) return;
		withCandidates = next;
		syncUrl();
		void loadAll();
	}
	function setView(next: ViewMode) {
		if (next === view) return;
		view = next;
		syncUrl();
	}

	// --- Open / step through the labeling pane --------------------------------
	function scrollSelectedIntoView() {
		if (!selectedKey) return;
		const id = rowElId(selectedKey);
		void tick().then(() => document.getElementById(id)?.scrollIntoView({ block: 'nearest' }));
	}

	function open(card: nav.PieceKey) {
		selectedKey = { machine_id: card.machine_id, piece_uuid: card.piece_uuid };
		syncUrl();
		scrollSelectedIntoView();
	}
	function closePane() {
		selectedKey = null;
		syncUrl();
	}

	async function selectByIndex(i: number) {
		while (i >= items.length && hasMore) await fetchMore();
		const target = items[i];
		if (target) open(target);
	}

	async function paneNext() {
		const i = selectedIndex;
		if (i < 0) {
			if (items.length > 0) open(items[0]);
			return;
		}
		if (i + 1 >= items.length && hasMore) await fetchMore();
		if (i + 1 < items.length) open(items[i + 1]);
		else closePane(); // reached the end of the list
	}

	async function panePrev() {
		const i = selectedIndex;
		if (i > 0) open(items[i - 1]);
	}

	// Reflect a just-saved label back onto the card without a refetch.
	function patchCard(key: nav.PieceKey, patch: PieceLabelPatch) {
		items = items.map((c) =>
			sameKey(c, key) ? { ...c, my_color: patch.my_color, my_crop: patch.my_crop } : c
		);
	}

	function startLabeling() {
		if (items.length > 0) open(items[0]);
	}

	// Infinite scroll — pull the next page as the sentinel nears the viewport.
	$effect(() => {
		const el = sentinel;
		if (!el) return;
		const obs = new IntersectionObserver(
			(entries) => {
				if (entries.some((e) => e.isIntersecting)) void fetchMore();
			},
			{ rootMargin: '600px' }
		);
		obs.observe(el);
		return () => obs.disconnect();
	});

	onMount(() => {
		void loadAll();

		// Machines list for the filter — session-cached, independent of filters.
		void nav
			.getMachinesCached()
			.then((m) => (machines = m))
			.catch(() => (machines = []));
	});
</script>

<svelte:head>
	<title>Piece Labeling · Hive</title>
</svelte:head>

<div class="mb-5 flex flex-wrap items-end justify-between gap-3">
	<div>
		<h1 class="text-2xl font-bold text-text">Piece Labeling</h1>
		<p class="text-sm text-text-muted">
			Label each synced piece — its true BrickLink color and which upstream crops are the same
			piece.
		</p>
	</div>
	<Button variant="primary" size="sm" onclick={startLabeling} disabled={loading || items.length === 0}>
		Start labeling <ArrowRight size={14} />
	</Button>
</div>

{#if error}
	<div class="mb-4 bg-primary/8 p-3 text-sm text-primary">{error}</div>
{/if}

<!-- Compact dashboard -->
{#if stats}
	<div class="mb-6 grid gap-3 border border-border bg-surface p-4 sm:grid-cols-[minmax(0,1fr)_auto]">
		<div>
			<div class="flex flex-wrap items-baseline gap-x-6 gap-y-1">
				<div>
					<span class="text-2xl font-bold text-text tabular-nums">{coverage}%</span>
					<span class="text-sm text-text-muted">color-labeled</span>
				</div>
				<div class="text-sm text-text-muted">
					<span class="text-text tabular-nums">{stats.color_labeled_pieces.toLocaleString()}</span>
					of {stats.total_labelable.toLocaleString()} pieces ·
					<span class="text-text tabular-nums">{stats.crop_linked_pieces.toLocaleString()}</span> same-piece
				</div>
			</div>
			<div class="mt-3 flex h-3 w-full overflow-hidden border border-border">
				<div class="bg-success" style={`width:${(hist['3+'] / histTotal) * 100}%`} title={`3+ labelers: ${hist['3+']}`}></div>
				<div class="bg-success/70" style={`width:${(hist['2'] / histTotal) * 100}%`} title={`2 labelers: ${hist['2']}`}></div>
				<div class="bg-success/40" style={`width:${(hist['1'] / histTotal) * 100}%`} title={`1 labeler: ${hist['1']}`}></div>
				<div class="bg-border" style={`width:${(hist['0'] / histTotal) * 100}%`} title={`unlabeled: ${hist['0']}`}></div>
			</div>
			<div class="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-text-muted">
				<span><span class="mr-1 inline-block h-2 w-2 bg-success align-middle"></span>3+ ({hist['3+']})</span>
				<span><span class="mr-1 inline-block h-2 w-2 bg-success/70 align-middle"></span>2 ({hist['2']})</span>
				<span><span class="mr-1 inline-block h-2 w-2 bg-success/40 align-middle"></span>1 ({hist['1']})</span>
				<span><span class="mr-1 inline-block h-2 w-2 bg-border align-middle"></span>0 ({hist['0'].toLocaleString()})</span>
			</div>
		</div>
		<div class="flex gap-6 border-t border-border pt-3 sm:border-l sm:border-t-0 sm:pl-6 sm:pt-0">
			<div>
				<div class="text-xl font-bold text-text tabular-nums">{stats.labeled_by_me.toLocaleString()}</div>
				<div class="text-xs text-text-muted">your colors</div>
			</div>
			<div>
				<div class="text-xl font-bold text-text tabular-nums">{stats.crop_links_by_me.toLocaleString()}</div>
				<div class="text-xs text-text-muted">your same-piece</div>
			</div>
		</div>
	</div>
{/if}

<!-- Palette coverage — for reviewers/admins: which colors are well-covered vs
     rare or missing in what's actually been labeled. -->
{#if auth.isReviewer}
	<PaletteCoverage {machineId} />
{/if}

{#snippet filterBtn(label: string, selected: boolean, onClick: () => void)}
	<button
		class="w-full px-2 py-1 text-left text-sm {selected
			? 'bg-primary-light font-medium text-primary'
			: 'text-text-muted hover:bg-bg hover:text-text'}"
		onclick={onClick}
	>
		{label}
	</button>
{/snippet}

<div class="flex flex-col gap-6 lg:flex-row lg:items-start">
	<!-- Filters (shared FilterGroup, same UI as the Channel Samples page) -->
	<aside class="flex shrink-0 flex-col gap-3 lg:w-60">
		<FilterGroup title="Sort" storageKey="pb-sort" active={sort !== 'priority'} activeLabel={sortLabel}>
			<div class="flex flex-col">
				{#each SORTS as s (s.value)}
					{@render filterBtn(s.label, sort === s.value, () => setSort(s.value))}
				{/each}
			</div>
		</FilterGroup>

		<FilterGroup title="Machine" storageKey="pb-machine" active={machineId !== null} activeLabel={machineName}>
			<div class="flex flex-col gap-2">
				{@render filterBtn('All machines', machineId === null, () => setMachine(null))}
				{#each machineGroups as [owner, group] (owner)}
					<div>
						<div class="px-2 pb-0.5 text-xs font-semibold uppercase tracking-wider text-text-muted">{owner}</div>
						{#each group as m (m.id)}
							{@render filterBtn(m.name, machineId === m.id, () => setMachine(m.id))}
						{/each}
					</div>
				{/each}
			</div>
		</FilterGroup>

		<FilterGroup title="Same piece" storageKey="pb-candidates" active={withCandidates} activeLabel={withCandidates ? 'Has candidates' : null}>
			<div class="flex flex-col">
				{@render filterBtn('All pieces', !withCandidates, () => setWithCandidates(false))}
				{@render filterBtn('Has candidate crops', withCandidates, () => setWithCandidates(true))}
			</div>
		</FilterGroup>
	</aside>

	<!-- List + optional labeling pane -->
	<div class="flex min-w-0 flex-1 flex-col gap-4 lg:flex-row lg:items-start">
		<!-- List column -->
		<div class="min-w-0 flex-1">
			<!-- View toggle -->
			<div class="mb-3 flex items-center justify-between gap-2">
				<span class="text-xs text-text-muted">
					{#if !loading}{items.length} shown{/if}
				</span>
				<div class="flex border border-border">
					<button
						type="button"
						title="Grid"
						onclick={() => setView('grid')}
						class="flex items-center gap-1 px-2 py-1 text-xs {view === 'grid'
							? 'bg-primary-light text-primary'
							: 'text-text-muted hover:bg-bg hover:text-text'}"
					>
						<LayoutGrid size={14} /> Grid
					</button>
					<button
						type="button"
						title="Rows"
						onclick={() => setView('rows')}
						class="flex items-center gap-1 border-l border-border px-2 py-1 text-xs {view === 'rows'
							? 'bg-primary-light text-primary'
							: 'text-text-muted hover:bg-bg hover:text-text'}"
					>
						<Rows3 size={14} /> Rows
					</button>
				</div>
			</div>

			{#if loading}
				<div class="flex justify-center py-16"><Spinner /></div>
			{:else if items.length === 0}
				<div class="border border-border bg-surface p-10 text-center">
					<p class="text-sm text-text-muted">No labelable pieces match these filters.</p>
				</div>
			{:else if view === 'grid'}
				<div
					class="grid grid-cols-2 gap-3 {paneOpen
						? 'sm:grid-cols-2 xl:grid-cols-3'
						: 'sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5'}"
				>
					{#each items as card (cardKey(card))}
						<PieceCard
							{card}
							id={rowElId(card)}
							selected={selectedKey != null && sameKey(card, selectedKey)}
							onOpen={open}
						/>
					{/each}
				</div>
			{:else}
				<div class="border border-border bg-surface">
					{#each items as card (cardKey(card))}
						<PieceRow
							{card}
							id={rowElId(card)}
							selected={selectedKey != null && sameKey(card, selectedKey)}
							onOpen={open}
						/>
					{/each}
				</div>
			{/if}

			{#if !loading && items.length > 0}
				<div class="mt-4 flex justify-center">
					{#if hasMore}
						<!-- Auto-fetch sentinel; the button is a manual fallback. -->
						<div bind:this={sentinel} class="flex justify-center py-2">
							<Button variant="secondary" size="sm" loading={fetchingMore} onclick={fetchMore}>
								Load more
							</Button>
						</div>
					{:else}
						<span class="text-xs text-text-muted">End of list · {items.length} shown</span>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Labeling pane (50/50) -->
		{#if paneOpen && selectedKey}
			<div class="min-w-0 flex-1 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto">
				{#key cardKey(selectedKey)}
					<PieceLabelPanel
						machineId={selectedKey.machine_id}
						pieceUuid={selectedKey.piece_uuid}
						layout="pane"
						position={panePosition}
						onNext={paneNext}
						onPrev={panePrev}
						onClose={closePane}
						onChange={patchCard}
					/>
				{/key}
			</div>
		{/if}
	</div>
</div>
