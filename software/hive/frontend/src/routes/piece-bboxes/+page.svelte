<script lang="ts">
	import { goto } from '$app/navigation';
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
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';
	import ArrowRight from 'lucide-svelte/icons/arrow-right';
	import Check from 'lucide-svelte/icons/check';
	import Link2 from 'lucide-svelte/icons/link-2';
	import Palette from 'lucide-svelte/icons/palette';
	import Sparkles from 'lucide-svelte/icons/sparkles';

	const BATCH = 60;

	const SORTS: { value: ColorLabelSort; label: string }[] = [
		{ value: 'priority', label: 'Priority (candidates, least-labeled)' },
		{ value: 'needs_me', label: 'Needs my label' },
		{ value: 'least_color', label: 'Fewest color labels' },
		{ value: 'most_color', label: 'Most color labels' },
		{ value: 'least_crop', label: 'Fewest same-piece labels' },
		{ value: 'most_crop', label: 'Most same-piece labels' },
		{ value: 'recent', label: 'Newest' },
		{ value: 'oldest', label: 'Oldest' }
	];

	let stats = $state<ColorLabelStats | null>(null);
	let machines = $state<Machine[]>([]);
	let sort = $state<ColorLabelSort>('priority');
	let machineId = $state<string | null>(null);
	// Default: only feed pieces that actually have a same-piece candidate list.
	let withCandidates = $state(true);
	let items = $state<ColorLabelPieceCard[]>([]);
	let hasMore = $state(true);
	let offset = 0;
	// Guards against duplicate keys — offset paging over a shifting/ties-heavy
	// order can re-return a piece, which would crash the keyed {#each}.
	let seenKeys = new Set<string>();

	function cardKey(c: ColorLabelPieceCard): string {
		return `${c.machine_id}|${c.piece_uuid}`;
	}
	let loading = $state(true);
	let fetchingMore = $state(false);
	let error = $state<string | null>(null);

	const coverage = $derived.by(() => {
		if (!stats || stats.total_labelable === 0) return 0;
		return Math.round((stats.color_labeled_pieces / stats.total_labelable) * 100);
	});
	const hist = $derived(stats?.labeler_histogram ?? { '0': 0, '1': 0, '2': 0, '3+': 0 });
	const histTotal = $derived(Math.max(1, stats?.total_labelable ?? 1));

	const sortLabel = $derived(SORTS.find((s) => s.value === sort)?.label ?? sort);
	const machineName = $derived(machines.find((m) => m.id === machineId)?.name ?? null);

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

	function currentFilters(): nav.NavFilters {
		return { sort, machineId, withCandidates };
	}

	async function loadAll() {
		loading = true;
		error = null;
		items = [];
		seenKeys = new Set();
		offset = 0;
		hasMore = true;
		try {
			const [s, page] = await Promise.all([
				api.colorLabelStats({ machineId }),
				api.colorLabelPieces({ sort, machineId, withCandidates, limit: BATCH, offset: 0 })
			]);
			stats = s;
			offset = page.items.length;
			hasMore = page.has_more;
			for (const c of page.items) {
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
		if (fetchingMore || !hasMore) return;
		fetchingMore = true;
		try {
			const page = await api.colorLabelPieces({ sort, machineId, withCandidates, limit: BATCH, offset });
			offset += page.items.length;
			hasMore = page.has_more;
			const fresh = page.items.filter((c) => !seenKeys.has(cardKey(c)));
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
		void loadAll();
	}
	function setMachine(next: string | null) {
		if (next === machineId) return;
		machineId = next;
		void loadAll();
	}
	function setWithCandidates(next: boolean) {
		if (next === withCandidates) return;
		withCandidates = next;
		void loadAll();
	}

	function open(card: ColorLabelPieceCard) {
		// Seed the working list so the piece view steps through this same filtered
		// order, then jump in.
		nav.seed(items, currentFilters(), offset, hasMore);
		void goto(`/piece-bboxes/${card.machine_id}/${encodeURIComponent(card.piece_uuid)}`);
	}
	function startLabeling() {
		if (items.length > 0) open(items[0]);
	}

	$effect(() => {
		void loadAll();
	});

	// Machines list for the filter — fetched once, independent of the filters.
	$effect(() => {
		void (async () => {
			try {
				machines = await api.getMachines({ scope: 'all' });
			} catch {
				machines = [];
			}
		})();
	});
</script>

<svelte:head>
	<title>Piece Labeling · Hive</title>
</svelte:head>

<div class="mb-5 flex flex-wrap items-end justify-between gap-3">
	<div>
		<h1 class="text-2xl font-bold text-text">Piece Labeling</h1>
		<p class="text-sm text-text-muted">
			Label each synced piece — its true BrickLink color and which upstream crops are the same piece.
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

	<!-- Grid -->
	<div class="min-w-0 flex-1">
		{#if loading}
			<div class="flex justify-center py-16"><Spinner /></div>
		{:else if items.length === 0}
			<div class="border border-border bg-surface p-10 text-center">
				<p class="text-sm text-text-muted">No labelable pieces match these filters.</p>
			</div>
		{:else}
			<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
				{#each items as card (card.machine_id + '|' + card.piece_uuid)}
					<button
						type="button"
						onclick={() => open(card)}
						class="group flex flex-col border border-border bg-surface p-2 text-left hover:border-primary"
					>
						<div class="relative flex h-24 w-full items-center justify-center bg-bg">
							{#if card.thumb_seq != null}
								<img
									src={api.colorLabelImageUrl(card.machine_id, card.piece_uuid, card.thumb_seq)}
									alt={card.part.part_name ?? 'piece'}
									loading="lazy"
									class="h-24 w-full bg-transparent object-contain"
								/>
							{:else}
								<span class="text-xs text-text-muted">no image</span>
							{/if}
							{#if card.has_candidates}
								<span class="absolute left-1 top-1 flex items-center bg-info/80 p-0.5 text-white" title="has same-piece candidate crops"><Sparkles size={11} /></span>
							{/if}
							{#if card.my_color}
								<span class="absolute right-1 top-1 flex items-center bg-success p-0.5 text-white" title="you labeled this"><Check size={12} /></span>
							{/if}
						</div>
						<div class="mt-1.5 truncate text-sm text-text" title={card.part.part_name ?? card.part.part_id ?? ''}>
							{card.part.part_name || card.part.part_id || 'Unidentified'}
						</div>
						<div class="mt-1 flex items-center gap-2 text-xs text-text-muted">
							<span class="flex items-center gap-1" title="color labels by users">
								<Palette size={13} />{card.color_label_count}
							</span>
							<span class="flex items-center gap-1" title="same-piece labels by users">
								<Link2 size={13} />{card.crop_link_count}
							</span>
							<span class="ml-auto truncate">· {card.machine_name ?? 'machine'}</span>
						</div>
					</button>
				{/each}
			</div>

			<div class="mt-4 flex justify-center">
				{#if hasMore}
					<Button variant="secondary" size="sm" loading={fetchingMore} onclick={fetchMore}>Load more</Button>
				{:else}
					<span class="text-xs text-text-muted">End of list · {items.length} shown</span>
				{/if}
			</div>
		{/if}
	</div>
</div>
