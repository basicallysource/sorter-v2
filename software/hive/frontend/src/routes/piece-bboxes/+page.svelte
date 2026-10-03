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
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import EmptyState from '$lib/components/EmptyState.svelte';
	import FilterOption from '$lib/components/FilterOption.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Shapes from '@lucide/svelte/icons/shapes';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import Rows3 from '@lucide/svelte/icons/rows-3';

	const BATCH = 60;

	const SORTS: { value: ColorLabelSort; label: string }[] = [
		{ value: 'priority', label: 'Priority: candidates, least labeled' },
		{ value: 'rare_color', label: 'Likely a rare color' },
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
	<title>Piece labeling - Hive</title>
</svelte:head>

<PageHeader title="Piece labeling" description="Label each synced piece: its true BrickLink color, and which earlier crops are the same piece.">
	{#snippet actions()}
		<Button variant="primary" icon={ArrowRight} onclick={startLabeling} disabled={loading || items.length === 0}>Start labeling</Button>
	{/snippet}
</PageHeader>

{#if error}<Alert tone="danger">{error}</Alert>{/if}

{#if stats}
	<Panel flush>
		<div class="grid gap-4 px-(--pad-panel) py-4 sm:grid-cols-[minmax(0,1fr)_auto]">
			<div>
				<div class="num flex flex-wrap items-baseline gap-x-6 gap-y-1">
					<div><span class="text-2xl font-semibold text-ink">{coverage}%</span> <span class="text-sm text-ink-muted">have a color</span></div>
					<div class="text-sm text-ink-muted">
						<span class="text-ink">{stats.color_labeled_pieces.toLocaleString()}</span> of {stats.total_labelable.toLocaleString()} pieces,
						<span class="text-ink">{stats.crop_linked_pieces.toLocaleString()}</span> with the same piece found
					</div>
				</div>
				<div class="mt-3 flex h-2 overflow-hidden rounded-item bg-track">
					{#each [
						{ key: '3+', cls: 'bg-success', label: '3 or more labelers' },
						{ key: '2', cls: 'bg-success/70', label: '2 labelers' },
						{ key: '1', cls: 'bg-success/40', label: '1 labeler' }
					] as bar (bar.key)}
						<div class={bar.cls} style={`width:${(hist[bar.key as keyof typeof hist] / histTotal) * 100}%`} title={`${bar.label}: ${hist[bar.key as keyof typeof hist]}`}></div>
					{/each}
				</div>
				<div class="num mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-ink-muted">
					<span class="flex items-center gap-1.5"><span class="size-2.5 rounded-full bg-success"></span>3 or more, {hist['3+']}</span>
					<span class="flex items-center gap-1.5"><span class="size-2.5 rounded-full bg-success/70"></span>2, {hist['2']}</span>
					<span class="flex items-center gap-1.5"><span class="size-2.5 rounded-full bg-success/40"></span>1, {hist['1']}</span>
					<span class="flex items-center gap-1.5"><span class="size-2.5 rounded-full bg-track"></span>None, {hist['0'].toLocaleString()}</span>
				</div>
			</div>
			<div class="num flex gap-6 border-t border-line pt-3 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-6">
				<div>
					<div class="text-xl font-semibold text-ink">{stats.labeled_by_me.toLocaleString()}</div>
					<div class="text-sm text-ink-muted">Your colors</div>
				</div>
				<div>
					<div class="text-xl font-semibold text-ink">{stats.crop_links_by_me.toLocaleString()}</div>
					<div class="text-sm text-ink-muted">Your same pieces</div>
				</div>
			</div>
		</div>
	</Panel>
{/if}

<!-- For reviewers: which colors are well covered, and which are rare or missing. -->
{#if auth.isReviewer}
	<PaletteCoverage {machineId} />
{/if}

<div class="flex flex-col gap-(--gap-panels) lg:flex-row lg:items-start">
	<!-- The filters, the same FilterGroups as the samples page -->
	<aside class="w-full shrink-0 lg:w-60">
		<div class="flex flex-col divide-y divide-line overflow-hidden rounded-panel bg-surface py-1">
			<FilterGroup title="Sort" storageKey="pb-sort" active={sort !== 'priority'} activeLabel={sortLabel}>
				<ul class="flex flex-col gap-px">
					{#each SORTS as option (option.value)}
						<FilterOption label={option.label} on={sort === option.value} onclick={() => setSort(option.value)} />
					{/each}
				</ul>
			</FilterGroup>
			<FilterGroup title="Machine" storageKey="pb-machine" active={machineId !== null} activeLabel={machineName}>
				<ul class="flex flex-col gap-px">
					<FilterOption label="All machines" on={machineId === null} onclick={() => setMachine(null)} />
					{#each machineGroups as [owner, group] (owner)}
						<li class="label px-2.5 pt-2 pb-1">{owner}</li>
						{#each group as m (m.id)}
							<FilterOption label={m.name} on={machineId === m.id} onclick={() => setMachine(m.id)} />
						{/each}
					{/each}
				</ul>
			</FilterGroup>
			<FilterGroup title="Same piece" storageKey="pb-candidates" active={withCandidates} activeLabel={withCandidates ? 'Has candidates' : null}>
				<ul class="flex flex-col gap-px">
					<FilterOption label="All pieces" on={!withCandidates} onclick={() => setWithCandidates(false)} />
					<FilterOption label="Has candidate crops" on={withCandidates} onclick={() => setWithCandidates(true)} />
				</ul>
			</FilterGroup>
		</div>
	</aside>

	<!-- The list, and the labeling pane beside it -->
	<div class="flex min-w-0 flex-1 flex-col gap-(--gap-panels) lg:flex-row lg:items-start">
		<div class="flex min-w-0 flex-1 flex-col gap-3">
			<div class="flex items-center justify-between gap-2">
				<span class="num text-sm text-ink-muted">{#if !loading}{items.length} shown{/if}</span>
				<SegmentedControl
					label="View"
					size="sm"
					value={view}
					options={[
						{ value: 'grid', label: 'Grid', icon: LayoutGrid },
						{ value: 'rows', label: 'Rows', icon: Rows3 }
					]}
					onchange={setView}
				/>
			</div>

			{#if loading}
				<div class="flex justify-center py-16"><Spinner size={32} /></div>
			{:else if items.length === 0}
				<Panel><EmptyState icon={Shapes} title="No pieces match">No labelable pieces match these filters.</EmptyState></Panel>
			{:else if view === 'grid'}
				<div class="grid grid-cols-[repeat(auto-fill,minmax(9rem,1fr))] gap-3">
					{#each items as card (cardKey(card))}
						<PieceCard {card} id={rowElId(card)} selected={selectedKey != null && sameKey(card, selectedKey)} onOpen={open} />
					{/each}
				</div>
			{:else}
				<div class="divide-y divide-line overflow-hidden rounded-panel bg-surface">
					{#each items as card (cardKey(card))}
						<PieceRow {card} id={rowElId(card)} selected={selectedKey != null && sameKey(card, selectedKey)} onOpen={open} />
					{/each}
				</div>
			{/if}

			{#if !loading && items.length > 0}
				<div class="flex justify-center">
					{#if hasMore}
						<!-- It fetches on its own as it scrolls into view; the button is the fallback. -->
						<div bind:this={sentinel} class="flex justify-center py-2">
							<Button size="sm" loading={fetchingMore} onclick={fetchMore}>Load more</Button>
						</div>
					{:else}
						<span class="num text-sm text-ink-muted">The end of the list, {items.length} shown</span>
					{/if}
				</div>
			{/if}
		</div>

		<!-- The labeling pane, half the width -->
		{#if paneOpen && selectedKey}
			<div
				class="min-w-0 flex-1 lg:sticky lg:top-[calc(var(--size-topbar)+1rem)] lg:max-h-[calc(100dvh-var(--size-topbar)-2rem)] lg:overflow-y-auto"
			>
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
