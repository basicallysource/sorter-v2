<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		api,
		type ColorLabelPieceCard,
		type ColorLabelSort,
		type ColorLabelStats
	} from '$lib/api';
	import * as nav from '$lib/colorLabelNav';
	import Spinner from '$lib/components/Spinner.svelte';
	import { Button } from '$lib/components/primitives';

	const BATCH = 60;

	const SORTS: { value: ColorLabelSort; label: string }[] = [
		{ value: 'needs_me', label: 'Needs my label' },
		{ value: 'least_color', label: 'Fewest color labels' },
		{ value: 'most_color', label: 'Most color labels' },
		{ value: 'least_crop', label: 'Fewest same-piece labels' },
		{ value: 'most_crop', label: 'Most same-piece labels' },
		{ value: 'recent', label: 'Newest' },
		{ value: 'oldest', label: 'Oldest' }
	];

	let stats = $state<ColorLabelStats | null>(null);
	let sort = $state<ColorLabelSort>('needs_me');
	let items = $state<ColorLabelPieceCard[]>([]);
	let hasMore = $state(true);
	let offset = 0;
	let loading = $state(true);
	let fetchingMore = $state(false);
	let error = $state<string | null>(null);

	const coverage = $derived.by(() => {
		if (!stats || stats.total_labelable === 0) return 0;
		return Math.round((stats.color_labeled_pieces / stats.total_labelable) * 100);
	});

	const hist = $derived(stats?.labeler_histogram ?? { '0': 0, '1': 0, '2': 0, '3+': 0 });
	const histTotal = $derived(Math.max(1, stats?.total_labelable ?? 1));

	function errMsg(e: unknown, fallback: string): string {
		return e && typeof e === 'object' && 'error' in e
			? String((e as { error: unknown }).error)
			: fallback;
	}

	async function loadAll() {
		loading = true;
		error = null;
		items = [];
		offset = 0;
		hasMore = true;
		try {
			const [s, page] = await Promise.all([
				api.colorLabelStats(),
				api.colorLabelPieces({ sort, limit: BATCH, offset: 0 })
			]);
			stats = s;
			items = page.items;
			offset = page.items.length;
			hasMore = page.has_more;
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
			const page = await api.colorLabelPieces({ sort, limit: BATCH, offset });
			offset += page.items.length;
			hasMore = page.has_more;
			items = [...items, ...page.items];
		} catch (e: unknown) {
			error = errMsg(e, 'Failed to load more pieces');
		} finally {
			fetchingMore = false;
		}
	}

	function changeSort(next: ColorLabelSort) {
		if (next === sort) return;
		sort = next;
		void loadAll();
	}

	function open(card: ColorLabelPieceCard) {
		// Seed the working list so the piece view can step through this same
		// order, then jump in.
		nav.seed(items, sort, offset, hasMore);
		void goto(`/color-labels/${card.machine_id}/${encodeURIComponent(card.piece_uuid)}`);
	}

	function startLabeling() {
		if (items.length > 0) open(items[0]);
	}

	$effect(() => {
		void loadAll();
	});
</script>

<svelte:head>
	<title>Color Labeling · Hive</title>
</svelte:head>

<div class="mb-5 flex flex-wrap items-end justify-between gap-3">
	<div>
		<h1 class="text-2xl font-bold text-text">Color Labeling</h1>
		<p class="text-sm text-text-muted">
			Label the true BrickLink color of each synced piece — and which upstream crops are the same piece.
		</p>
	</div>
	<Button variant="primary" size="sm" onclick={startLabeling} disabled={loading || items.length === 0}>
		Start labeling →
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
			<!-- Coverage by number of labelers -->
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

<!-- Sort + grid -->
<div class="mb-3 flex flex-wrap items-center gap-2">
	<span class="text-xs font-semibold uppercase tracking-wider text-text-muted">Sort</span>
	{#each SORTS as s (s.value)}
		<button
			class="border px-2.5 py-1 text-sm {sort === s.value
				? 'border-primary bg-primary/8 text-text'
				: 'border-border text-text-muted hover:text-text'}"
			onclick={() => changeSort(s.value)}
		>
			{s.label}
		</button>
	{/each}
</div>

{#if loading}
	<div class="flex justify-center py-16"><Spinner /></div>
{:else if items.length === 0}
	<div class="border border-border bg-surface p-10 text-center">
		<p class="text-sm text-text-muted">No labelable pieces yet.</p>
	</div>
{:else}
	<div class="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6">
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
					{#if card.my_color}
						<span class="absolute right-1 top-1 bg-success px-1 text-xs leading-tight text-white">✓</span>
					{/if}
				</div>
				<div class="mt-1.5 truncate text-sm text-text" title={card.part.part_name ?? card.part.part_id ?? ''}>
					{card.part.part_name || card.part.part_id || 'Unidentified'}
				</div>
				<div class="mt-1 flex items-center gap-2 text-xs text-text-muted">
					<span title="color labels by users">🎨 {card.color_label_count}</span>
					<span title="same-piece labels by users">🔗 {card.crop_link_count}</span>
					<span class="ml-auto">· {card.machine_name ?? 'machine'}</span>
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
