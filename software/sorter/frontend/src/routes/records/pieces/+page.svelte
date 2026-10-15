<script lang="ts">
	import { tick } from 'svelte';
	import Download from '@lucide/svelte/icons/download';
	import RefreshCw from '@lucide/svelte/icons/refresh-cw';
	import PieceFilters from '$lib/components/records/PieceFilters.svelte';
	import PieceRow from '$lib/components/records/PieceRow.svelte';
	import Alert from '$lib/components/ui/Alert.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import Pager from '$lib/components/ui/Pager.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import { getMachineContext } from '$lib/machines/context';
	import { pieceStore, type PieceSummary } from '$lib/pieces';
	import { ImageHydrator } from '$lib/records/image-hydrator.svelte';
	import { recordsBase } from '$lib/records/base';
	import { pieceFilterKeys, toPieceQuery } from '$lib/records/piece-filters';
	import { RecordsList } from '$lib/records/records-list.svelte';
	import { scrollerOf } from '$lib/records/scroll';

	const ctx = getMachineContext();
	const base = recordsBase();

	// A page is a long scroll: rows are cheap to draw, and pictures load only for
	// the rows near the screen.
	const PAGE_SIZE = 250;

	const list = new RecordsList<PieceSummary>({
		base,
		path: '/api/pieces',
		pageSize: PAGE_SIZE,
		filters: pieceFilterKeys,
		toQuery: toPieceQuery
	});
	const images = new ImageHydrator(base);

	let root = $state<HTMLElement | null>(null);
	let expandedReclassify = $state<Set<string>>(new Set());

	function toggleReclassify(uuid: string) {
		const next = new Set(expandedReclassify);
		if (next.has(uuid)) next.delete(uuid);
		else next.add(uuid);
		expandedReclassify = next;
	}

	// A correction returns the fresh summary: update the listed row in place and
	// feed the store, so the dashboard's recent pieces reflect it too.
	function onPieceCorrected(summary: PieceSummary) {
		list.items = list.items.map((it) => (it.uuid === summary.uuid ? { ...it, ...summary } : it));
		const mid = ctx.machine?.identity?.machine_id ?? null;
		if (mid) pieceStore.upsertFromRest(mid, [summary]);
	}

	// The pictures of the pieces on this page, for the rows near the screen.
	$effect(() => {
		images.keepOnly(list.items.map((p) => p.uuid));
	});

	// --- Scroll -----------------------------------------------------------------
	// Going to another page brings the top of the list into sight, and coming Back
	// from a piece puts the list where it was.
	const scroller = () => scrollerOf(root);

	let seenTurned = list.turned;
	$effect(() => {
		if (list.turned === seenTurned) return;
		seenTurned = list.turned;
		void tick().then(() => root?.scrollIntoView({ block: 'start' }));
	});

	let restoreTop = $state<number | null>(null);
	$effect(() => {
		if (restoreTop == null || list.loading || list.items.length === 0) return;
		const top = restoreTop;
		restoreTop = null;
		void tick().then(() => scroller()?.scrollTo({ top }));
	});

	export const snapshot = {
		capture: () => scroller()?.scrollTop ?? 0,
		restore: (top: number) => {
			restoreTop = top;
		}
	};

	const filtering = $derived(Object.keys(list.filters).length > 0);
	function clearFilters() {
		list.setFilters(Object.fromEntries(pieceFilterKeys.map((key) => [key, null])));
	}

	// The export is the list: the same filters, cut at the same anchor.
	const exportUrl = $derived(`${base()}/api/pieces/export.csv?${list.query}`);
</script>

<svelte:head>
	<title>Pieces - Records - Sorter</title>
</svelte:head>

{#snippet pager()}
	<Pager
		label="Pieces"
		noun={filtering ? 'matching pieces' : 'pieces'}
		page={list.pageIndex + 1}
		pages={list.pageCount}
		from={list.from}
		to={list.to}
		total={list.total}
		loading={list.loading}
		jump={list.canJump}
		onpage={(n) => list.open(n - 1)}
	/>
{/snippet}

<div bind:this={root} class="flex flex-col gap-(--gap-panels)">
	<PieceFilters {list} {base} />

	<div class="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
		<div class="flex items-center gap-3 text-sm text-ink-muted">
			{#if list.loading}<Spinner size={14} /> Loading the pieces{/if}
			{#if list.newer}
				<span class="num">
					{list.newer.toLocaleString()} newer {list.newer === 1 ? 'piece' : 'pieces'} arrived since this
					list started
				</span>
				<Button size="sm" icon={RefreshCw} onclick={() => list.refresh()}>Show them</Button>
			{/if}
		</div>
		<div class="flex flex-wrap items-center justify-end gap-x-4 gap-y-2">
			<Button size="sm" icon={Download} href={exportUrl} download>Export CSV</Button>
			{@render pager()}
		</div>
	</div>

	{#if list.failed}
		<Alert tone="warning" title="Could not load the pieces">
			The machine did not answer.
			{#snippet actions()}
				<Button size="sm" onclick={() => list.reload()}>Try again</Button>
			{/snippet}
		</Alert>
	{/if}

	{#if list.items.length === 0}
		<EmptyState
			title={list.loading ? 'Loading the pieces' : filtering ? 'No pieces match' : 'No pieces'}
		>
			{#snippet action()}
				{#if filtering && !list.loading}
					<Button size="sm" onclick={clearFilters}>Clear filters</Button>
				{/if}
			{/snippet}
		</EmptyState>
	{:else}
		<Panel flush>
			<div class="divide-y divide-line">
				{#each list.items as piece (piece.uuid)}
					<PieceRow
						{piece}
						imgState={images.states[piece.uuid]}
						endpointBase={base()}
						reclassifyOpen={expandedReclassify.has(piece.uuid)}
						onToggleReclassify={() => toggleReclassify(piece.uuid)}
						{onPieceCorrected}
						onnear={() => images.want({ uuid: piece.uuid, seen_at: piece.seen_at ?? null })}
						onleave={() => images.unwant(piece.uuid)}
					/>
				{/each}
			</div>
		</Panel>
		<div class="flex justify-end">{@render pager()}</div>
	{/if}
</div>
