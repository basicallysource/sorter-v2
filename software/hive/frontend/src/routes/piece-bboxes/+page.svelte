<script lang="ts">
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import { api, type ColorLabelSort, type ColorLabelStats, type Machine } from '$lib/api';
	import { auth } from '$lib/auth.svelte';
	import * as nav from '$lib/colorLabelNav';
	import FilterGroup from '$lib/components/FilterGroup.svelte';
	import MachineFilter from '$lib/components/MachineFilter.svelte';
	import PaletteCoverage from '$lib/components/PaletteCoverage.svelte';
	import PieceCard from '$lib/components/PieceCard.svelte';
	import PieceLabelPanel, { type PieceLabelPatch } from '$lib/components/PieceLabelPanel.svelte';
	import PieceRow from '$lib/components/PieceRow.svelte';
	import ReviewGrid from '$lib/components/ReviewGrid.svelte';
	import Button from '$lib/components/Button.svelte';
	import Alert from '$lib/components/Alert.svelte';
	import FilterOption from '$lib/components/FilterOption.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Panel from '$lib/components/Panel.svelte';
	import SegmentedControl from '$lib/components/SegmentedControl.svelte';
	import Shapes from '@lucide/svelte/icons/shapes';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import LayoutGrid from '@lucide/svelte/icons/layout-grid';
	import Rows3 from '@lucide/svelte/icons/rows-3';

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

	// The filters live in the URL, so a shared, reloaded or back-navigated link
	// shows the same list. Defaults: priority sort, every machine, has-candidates.
	let filters = $state<nav.PieceFilters>(nav.filtersFromSearch(page.url.searchParams));
	let view = $state<ViewMode>(page.url.searchParams.get('view') === 'rows' ? 'rows' : 'grid');
	// The piece open in the labeling pane (a key, so a shared URL can open a
	// piece that is not in the list yet).
	let selectedKey = $state<nav.PieceKey | null>(parsePieceParam(page.url.searchParams));
	const paneOpen = $derived(selectedKey != null);

	// One queue per set of filters, shared with the pane: a new filter is a new
	// queue, and nothing still on its way for the old one can reach this list.
	const queue = $derived(nav.pieceQueue(filters));

	let stats = $state<ColorLabelStats | null>(null);
	let statsError = $state<string | null>(null);
	let machines = $state<Machine[]>([]);

	function rowElId(c: nav.PieceKey): string {
		return `pb-${c.machine_id}-${c.piece_uuid}`;
	}

	const coverage = $derived.by(() => {
		if (!stats || stats.total_labelable === 0) return 0;
		return Math.round((stats.color_labeled_pieces / stats.total_labelable) * 100);
	});
	const hist = $derived(stats?.labeler_histogram ?? { '0': 0, '1': 0, '2': 0, '3+': 0 });
	const histTotal = $derived(Math.max(1, stats?.total_labelable ?? 1));

	const sortLabel = $derived(SORTS.find((s) => s.value === filters.sort)?.label ?? filters.sort);
	const panePosition = $derived(selectedKey ? queue.position(nav.pieceKey(selectedKey)) : { index: -1, total: 0, hasMore: true });

	function parsePieceParam(sp: URLSearchParams): nav.PieceKey | null {
		const pm = sp.get('pm');
		const pu = sp.get('pu');
		return pm && pu ? { machine_id: pm, piece_uuid: pu } : null;
	}

	// Mirror filters, view and open piece into the URL (replace, not push: these
	// are not history entries).
	function syncUrl() {
		const params = nav.filtersToSearch(filters);
		if (view === 'rows') params.set('view', 'rows');
		if (selectedKey) {
			params.set('pm', selectedKey.machine_id);
			params.set('pu', selectedKey.piece_uuid);
		}
		const qs = params.toString();
		replaceState(`/piece-bboxes${qs ? `?${qs}` : ''}`, {});
	}

	// The counts follow the machine filter; only the newest answer is shown.
	let statsToken = 0;
	async function loadStats(machineIds: string[]) {
		const token = ++statsToken;
		statsError = null;
		try {
			const s = await api.colorLabelStats({ machineIds });
			if (token === statsToken) stats = s;
		} catch (e: unknown) {
			if (token === statsToken) {
				statsError = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to load the counts';
			}
		}
	}

	function setFilters(next: Partial<nav.PieceFilters>) {
		filters = { ...filters, ...next };
		syncUrl();
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

	async function paneNext() {
		if (!selectedKey) return;
		const next = await queue.after(nav.pieceKey(selectedKey));
		if (next) open(next);
		else closePane(); // the end of the list
	}

	function panePrev() {
		if (!selectedKey) return;
		const prev = queue.before(nav.pieceKey(selectedKey));
		if (prev) open(prev);
	}

	// Reflect a just-saved label back onto the card without a refetch.
	function patchCard(key: nav.PieceKey, patch: PieceLabelPatch) {
		queue.patch(nav.pieceKey(key), (c) => ({ ...c, my_color: patch.my_color, my_crop: patch.my_crop }));
	}

	function startLabeling() {
		if (queue.items.length > 0) open(queue.items[0]);
	}

	// Load the list for the current filters (a queue already loaded for them,
	// say on coming back to the page, is kept as it is).
	$effect(() => {
		void queue.start();
	});

	const machinesKey = $derived(filters.machineIds.join(','));
	$effect(() => {
		void loadStats(machinesKey ? machinesKey.split(',') : []);
	});

	onMount(() => {
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
		<Button variant="primary" icon={ArrowRight} onclick={startLabeling} disabled={queue.loading || queue.items.length === 0}>Start labeling</Button>
	{/snippet}
</PageHeader>

{#if statsError}<Alert tone="danger">{statsError}</Alert>{/if}

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
	<PaletteCoverage machineIds={filters.machineIds} />
{/if}

<div class="flex flex-col gap-(--gap-panels) lg:flex-row lg:items-start">
	<!-- The filters, the same FilterGroups as the samples page -->
	<aside class="w-full shrink-0 lg:w-60">
		<div class="flex flex-col divide-y divide-line overflow-hidden rounded-panel bg-surface py-1">
			<FilterGroup title="Sort" storageKey="pb-sort" active={filters.sort !== 'priority'} activeLabel={sortLabel}>
				<ul class="flex flex-col gap-px">
					{#each SORTS as option (option.value)}
						<FilterOption label={option.label} on={filters.sort === option.value} onclick={() => setFilters({ sort: option.value })} />
					{/each}
				</ul>
			</FilterGroup>
			<MachineFilter {machines} selected={filters.machineIds} onchange={(ids) => setFilters({ machineIds: ids })} storageKey="pb-machine" />
			<FilterGroup title="Same piece" storageKey="pb-candidates" active={filters.withCandidates} activeLabel={filters.withCandidates ? 'Has candidates' : null}>
				<ul class="flex flex-col gap-px">
					<FilterOption label="All pieces" on={!filters.withCandidates} onclick={() => setFilters({ withCandidates: false })} />
					<FilterOption label="Has candidate crops" on={filters.withCandidates} onclick={() => setFilters({ withCandidates: true })} />
				</ul>
			</FilterGroup>
		</div>
	</aside>

	<!-- The list, and the labeling pane beside it -->
	<div class="flex min-w-0 flex-1 flex-col gap-(--gap-panels) lg:flex-row lg:items-start">
		<div class="flex min-w-0 flex-1 flex-col gap-3">
			<div class="flex items-center justify-between gap-2">
				<span class="num text-sm text-ink-muted">{#if !queue.loading}{queue.items.length} shown{/if}</span>
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

			<ReviewGrid {queue} layout={view} emptyIcon={Shapes} emptyTitle="No pieces match">
				{#snippet empty()}No labelable pieces match these filters.{/snippet}
				{#snippet item(card)}
					{@const selected = selectedKey != null && nav.pieceKey(card) === nav.pieceKey(selectedKey)}
					{#if view === 'grid'}
						<PieceCard {card} id={rowElId(card)} {selected} onOpen={open} />
					{:else}
						<PieceRow {card} id={rowElId(card)} {selected} onOpen={open} />
					{/if}
				{/snippet}
			</ReviewGrid>
		</div>

		<!-- The labeling pane, half the width -->
		{#if paneOpen && selectedKey}
			<div
				class="min-w-0 flex-1 lg:sticky lg:top-[calc(var(--size-topbar)+1rem)] lg:max-h-[calc(100dvh-var(--size-topbar)-2rem)] lg:overflow-y-auto"
			>
				{#key nav.pieceKey(selectedKey)}
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
