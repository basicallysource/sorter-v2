<script lang="ts">
	import { replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount, tick } from 'svelte';
	import {
		api,
		type ColorLabelPieceCard,
		type ColorLabelSort,
		type ColorLabelStats,
		type ColorModelChoice,
		type Machine
	} from '$lib/api';
	import { modelLabel } from '$lib/colorModels';
	import { prefetchPiece, prefetchPieces } from '$lib/pieceCache';
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
	import Select from '$lib/components/Select.svelte';
	import Shapes from '@lucide/svelte/icons/shapes';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import Check from '@lucide/svelte/icons/check';
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
		{ value: 'oldest', label: 'Oldest' },
		{ value: 'least_sure', label: 'A color model: least sure first' },
		{ value: 'surest', label: 'A color model: surest first' }
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

	// The colour models the list can sort by and show on its cards.
	let colorModels = $state<ColorModelChoice[]>([]);
	const isModelSort = $derived(nav.MODEL_SORTS.includes(filters.sort));
	const modelOptions = $derived([
		{ value: '', label: 'No color model' },
		...colorModels.map((m) => ({ value: m.sha256, label: `${modelLabel(m.name)}${m.is_active ? ' (active)' : ''}`, hint: m.name }))
	]);

	function activeModel(): string | null {
		return colorModels.find((m) => m.is_active)?.sha256 ?? colorModels[0]?.sha256 ?? null;
	}

	// A model chosen sorts by it, least sure first, unless a model sort is on already.
	function chooseModel(sha: string) {
		if (!sha) setFilters({ colorModel: null, sort: isModelSort ? 'priority' : filters.sort });
		else setFilters({ colorModel: sha, sort: isModelSort ? filters.sort : 'least_sure' });
	}
	function chooseOrder(order: string) {
		setFilters({ sort: order === 'list' ? 'priority' : (order as ColorLabelSort) });
	}
	// A model sort picked from the list of sorts is by the active model until another is chosen.
	function chooseSort(sort: ColorLabelSort) {
		const needsModel = nav.MODEL_SORTS.includes(sort) && !filters.colorModel;
		setFilters(needsModel ? { sort, colorModel: activeModel() } : { sort });
	}

	// Pieces picked for "agree with the model": only cards with the model's
	// answer can be picked, and a new list starts with none.
	const AGREE_MAX = 500;
	let picked = $state<Set<string>>(new Set());
	let pickAnchor: string | null = null;
	let agreeing = $state(false);
	let agreeNote = $state<string | null>(null);
	$effect(() => {
		void queue;
		picked = new Set();
		pickAnchor = null;
	});
	const pickedCards = $derived(queue.items.filter((c) => picked.has(nav.pieceKey(c))));
	const pickableCount = $derived(queue.items.filter((c) => c.model_color).length);
	const chosenModel = $derived(colorModels.find((m) => m.sha256 === filters.colorModel) ?? null);
	// "These are Red" when every picked piece is the same colour to the model.
	const agreeLabel = $derived.by(() => {
		const names = new Set(pickedCards.map((c) => c.model_color?.color_name ?? String(c.model_color?.color_id)));
		const n = pickedCards.length;
		if (names.size === 1) return `These are ${[...names][0]}: agree (${n})`;
		return `Agree with ${chosenModel ? modelLabel(chosenModel.name) : 'the model'} (${n})`;
	});

	function pick(card: ColorLabelPieceCard, range: boolean) {
		const key = nav.pieceKey(card);
		const next = new Set(picked);
		const on = !next.has(key);
		const items = queue.items;
		const from = range && pickAnchor ? items.findIndex((c) => nav.pieceKey(c) === pickAnchor) : -1;
		const to = items.findIndex((c) => nav.pieceKey(c) === key);
		// A shift-click gives the stretch from the last pick to this one this
		// one's new state (picked, or not), as its box now shows.
		const stretch = from >= 0 && to >= 0 ? items.slice(Math.min(from, to), Math.max(from, to) + 1) : [card];
		for (const c of stretch) {
			if (!c.model_color) continue;
			if (on) next.add(nav.pieceKey(c));
			else next.delete(nav.pieceKey(c));
		}
		pickAnchor = key;
		picked = next;
		agreeNote = null;
	}
	function pickAllShown() {
		picked = new Set(queue.items.filter((c) => c.model_color).map((c) => nav.pieceKey(c)));
		agreeNote = null;
	}
	function clearPicks() {
		picked = new Set();
		pickAnchor = null;
	}

	async function agree() {
		if (!filters.colorModel || pickedCards.length === 0 || pickedCards.length > AGREE_MAX) return;
		agreeing = true;
		agreeNote = null;
		try {
			const res = await api.colorLabelAgree(
				filters.colorModel,
				pickedCards.map((c) => ({ machine_id: c.machine_id, piece_uuid: c.piece_uuid }))
			);
			for (const l of res.labels) {
				queue.patch(nav.pieceKey(l), (c) => ({
					...c,
					my_color: true,
					color_label_count: c.color_label_count + (l.created ? 1 : 0)
				}));
			}
			agreeNote = `Labeled ${res.labeled.toLocaleString()}${res.skipped ? `, ${res.skipped} skipped` : ''}.`;
			clearPicks();
			void loadStats(filters.machineIds);
		} catch (e: unknown) {
			agreeNote = e && typeof e === 'object' && 'error' in e ? String((e as { error: unknown }).error) : 'Failed to save the labels';
		} finally {
			agreeing = false;
		}
	}

	// Opening a piece should be instant: the next few after the open one, and a
	// card the pointer rests on, are fetched ahead (lib/pieceCache).
	const PREFETCH_NEXT = 3;
	let hoverTimer: ReturnType<typeof setTimeout> | null = null;
	function hover(card: ColorLabelPieceCard | null) {
		if (hoverTimer) clearTimeout(hoverTimer);
		hoverTimer = card ? setTimeout(() => prefetchPiece(card.machine_id, card.piece_uuid), 120) : null;
	}
	$effect(() => {
		const key = selectedKey;
		const items = queue.items;
		if (!key) return;
		const at = items.findIndex((c) => nav.pieceKey(c) === nav.pieceKey(key));
		if (at >= 0) prefetchPieces(items.slice(at + 1, at + 1 + PREFETCH_NEXT));
	});

	let stats = $state<ColorLabelStats | null>(null);
	let statsError = $state<string | null>(null);
	let machines = $state<Machine[]>([]);

	function rowElId(c: nav.PieceKey): string {
		return `pb-${c.machine_id}-${c.piece_uuid}`;
	}

	// A training run's color counts as a color label.
	const colored = $derived((stats?.color_labeled_pieces ?? 0) + (stats?.training_labeled_pieces ?? 0));
	const coverage = $derived.by(() => {
		if (!stats || stats.total_labelable === 0) return 0;
		return Math.min(100, Math.round((colored / stats.total_labelable) * 100));
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
		void nav
			.getColorModels()
			.then((m) => {
				colorModels = m;
				// A model sort from a link that names no model is by the active one: say so.
				if (isModelSort && !filters.colorModel && activeModel()) setFilters({ colorModel: activeModel() });
			})
			.catch(() => (colorModels = []));
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
						<span class="text-ink">{colored.toLocaleString()}</span> of {stats.total_labelable.toLocaleString()} pieces{#if stats.training_labeled_pieces > 0}
							({stats.training_labeled_pieces.toLocaleString()} from training runs){/if},
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
						<FilterOption label={option.label} on={filters.sort === option.value} onclick={() => chooseSort(option.value)} />
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
			<!-- A classification frame of the piece's machine within two hours of it had the reference palette in view. -->
			<FilterGroup title="Color palette" storageKey="pb-palette" active={filters.withPalette} activeLabel={filters.withPalette ? 'In view' : null}>
				<ul class="flex flex-col gap-px">
					<FilterOption label="Any" on={!filters.withPalette} onclick={() => setFilters({ withPalette: false })} />
					<FilterOption label="In view" on={filters.withPalette} onclick={() => setFilters({ withPalette: true })} />
				</ul>
			</FilterGroup>
		</div>
	</aside>

	<!-- The list, and the labeling pane beside it -->
	<div class="flex min-w-0 flex-1 flex-col gap-(--gap-panels) lg:flex-row lg:items-start">
		<div class="flex min-w-0 flex-1 flex-col gap-3">
			<div class="flex items-center justify-between gap-2">
				<div class="flex min-w-0 flex-wrap items-center gap-2">
					<span class="num text-sm text-ink-muted">{#if !queue.loading}{queue.items.length} shown{/if}</span>
					<!-- A colour model: its answer on every card, and the list by its confidence -->
					{#if colorModels.length > 0}
						<Select
							size="sm"
							label="Color model"
							class="w-52"
							value={filters.colorModel ?? ''}
							options={modelOptions}
							onchange={chooseModel}
						/>
						{#if filters.colorModel}
							<Select
								size="sm"
								label="Order"
								class="w-44"
								value={isModelSort ? filters.sort : 'list'}
								options={[
									{ value: 'least_sure', label: 'Least sure first' },
									{ value: 'surest', label: 'Surest first' },
									{ value: 'list', label: "The list's sort" }
								]}
								onchange={chooseOrder}
							/>
						{/if}
					{/if}
				</div>
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

			<!-- Agree in bulk with the chosen model's colors -->
			{#if filters.colorModel && (pickableCount > 0 || agreeNote)}
				<div class="flex flex-wrap items-center gap-2 rounded-panel bg-surface px-(--pad-panel) py-2 text-sm">
					{#if picked.size > 0}
						<Button
							size="sm"
							variant="primary"
							icon={Check}
							loading={agreeing}
							disabled={picked.size > AGREE_MAX}
							title={picked.size > AGREE_MAX ? `At most ${AGREE_MAX} at a time` : 'Label each picked piece with the color the model gave it'}
							onclick={agree}>{agreeLabel}</Button
						>
						<Button size="sm" variant="ghost" onclick={clearPicks}>Clear</Button>
					{:else}
						<span class="text-ink-muted">Pick pieces the model got right (shift-click picks a range).</span>
					{/if}
					{#if picked.size < pickableCount}
						<Button size="sm" variant="ghost" onclick={pickAllShown}>Pick all shown ({pickableCount.toLocaleString()})</Button>
					{/if}
					{#if agreeNote}<span class="text-ink-muted">{agreeNote}</span>{/if}
				</div>
			{/if}

			<ReviewGrid {queue} layout={view} emptyIcon={Shapes} emptyTitle="No pieces match">
				{#snippet empty()}{isModelSort ? 'This color model has not read any of these pieces yet.' : 'No labelable pieces match these filters.'}{/snippet}
				{#snippet item(card)}
					{@const selected = selectedKey != null && nav.pieceKey(card) === nav.pieceKey(selectedKey)}
					{#if view === 'grid'}
						<PieceCard
							{card}
							id={rowElId(card)}
							{selected}
							onOpen={open}
							picked={picked.has(nav.pieceKey(card))}
							onPick={filters.colorModel && card.model_color ? pick : undefined}
							onHover={hover}
						/>
					{:else}
						<PieceRow
							{card}
							id={rowElId(card)}
							{selected}
							onOpen={open}
							picked={picked.has(nav.pieceKey(card))}
							onPick={filters.colorModel && card.model_color ? pick : undefined}
							onHover={hover}
						/>
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
