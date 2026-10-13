<script lang="ts">
	import { onMount } from 'svelte';
	import ArrowLeft from '@lucide/svelte/icons/arrow-left';
	import Square from '@lucide/svelte/icons/square';
	import { getBackendHttpBase, machineHttpBaseUrlFromWsUrl } from '$lib/backend';
	import { getMachineContext } from '$lib/machines/context';
	import { fetchLegoColors } from '$lib/pieces/colors';
	import Badge from '$lib/components/ui/Badge.svelte';
	import Button from '$lib/components/ui/Button.svelte';
	import PageHeader from '$lib/components/ui/PageHeader.svelte';
	import Panel from '$lib/components/ui/Panel.svelte';
	import SegmentedControl from '$lib/components/ui/SegmentedControl.svelte';
	import Spinner from '$lib/components/ui/Spinner.svelte';
	import RunColors from '$lib/components/training/RunColors.svelte';
	import PieceFeed from '$lib/components/training/PieceFeed.svelte';
	import {
		PAGE_SIZE,
		endRun,
		formatDuration,
		formatTime,
		formatWhen,
		getRunPieces,
		setPieceExcluded,
		setRunExcluded,
		type PieceFilter,
		type TrainingPiece,
		type TrainingRun
	} from '$lib/training/api';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();

	const machine = getMachineContext();

	const POLL_MS = 3000;
	const FILTERS: { value: PieceFilter; label: string }[] = [
		{ value: 'all', label: 'All' },
		{ value: 'disagree', label: 'Disagrees with the machine' },
		{ value: 'excluded', label: 'Excluded' }
	];
	const EMPTY: Record<PieceFilter, string> = {
		all: 'No pieces yet.',
		disagree: 'No piece disagrees with the machine.',
		excluded: 'No piece is excluded.'
	};

	const base = $derived(machineHttpBaseUrlFromWsUrl(machine.machine?.url) ?? getBackendHttpBase());

	let filter = $state<PieceFilter>('all');
	let run = $state<TrainingRun | null>(null);
	let pieces = $state<TrainingPiece[]>([]);
	let total = $state(0);
	let loading = $state(true);
	let loadingMore = $state(false);
	let runBusy = $state(false);
	let ending = $state(false);
	let error = $state<string | null>(null);

	// While the pointer is over the pieces, a refresh waits, so nothing moves
	// under a click.
	let held = false;
	let request = 0;

	function message(e: unknown): string {
		return e instanceof Error ? e.message : String(e);
	}

	// The first page for the filter; `quiet` refreshes without the spinner.
	async function load(quiet = false) {
		const mine = ++request;
		if (!quiet) loading = true;
		try {
			const res = await getRunPieces(base, data.id, { filter });
			if (mine !== request) return;
			run = res.run;
			pieces = res.pieces;
			total = res.total;
			error = null;
		} catch (e) {
			if (mine === request && !quiet) error = `Couldn't load the run: ${message(e)}`;
		} finally {
			if (mine === request) loading = false;
		}
	}

	async function loadMore() {
		loadingMore = true;
		try {
			const res = await getRunPieces(base, data.id, { filter, offset: pieces.length });
			const have = new Set(pieces.map((p) => p.uuid));
			run = res.run;
			total = res.total;
			pieces = [...pieces, ...res.pieces.filter((p) => !have.has(p.uuid))];
		} catch (e) {
			error = `Couldn't load more pieces: ${message(e)}`;
		} finally {
			loadingMore = false;
		}
	}

	async function togglePiece(piece: TrainingPiece) {
		error = null;
		try {
			const next = await setPieceExcluded(base, piece.uuid, !piece.training_excluded);
			pieces = pieces.map((p) => (p.uuid === next.uuid ? next : p));
			if (run && next.training_excluded !== piece.training_excluded) {
				const step = next.training_excluded ? 1 : -1;
				run = {
					...run,
					excluded_pieces: run.excluded_pieces + step,
					labeled: run.labeled - (next.training_color_id ? step : 0)
				};
			}
		} catch (e) {
			error = message(e);
		}
	}

	async function toggleRun() {
		if (!run) return;
		runBusy = true;
		error = null;
		try {
			run = await setRunExcluded(base, run.id, !run.excluded);
		} catch (e) {
			error = message(e);
		} finally {
			runBusy = false;
		}
	}

	async function end() {
		if (!run) return;
		ending = true;
		error = null;
		try {
			await endRun(base, run.id);
			await load(true);
		} catch (e) {
			error = message(e);
		} finally {
			ending = false;
		}
	}

	// A new filter, run or machine starts from the first page.
	$effect(() => {
		void [base, data.id, filter];
		pieces = [];
		void load();
	});

	// The swatches on the pieces come from the machine's palette.
	$effect(() => {
		fetchLegoColors(base).catch(() => {});
	});

	// While the run collects, its newest pieces come in, until more are loaded.
	onMount(() => {
		const timer = setInterval(() => {
			if (run?.collecting && !held && !loading && !loadingMore && pieces.length <= PAGE_SIZE) {
				void load(true);
			}
		}, POLL_MS);
		return () => clearInterval(timer);
	});
</script>

<svelte:head><title>Sorter - Training run</title></svelte:head>

<PageHeader
	title={run ? `Run from ${formatWhen(run.started_at)}` : 'Training run'}
	description="Every piece the machine saw during this run, labeled with the color of its segment. Click a piece to exclude it, and again to bring it back."
>
	{#snippet actions()}
		<Button icon={ArrowLeft} href="/settings/training-data">Back to training data</Button>
		{#if run?.collecting}
			<Button icon={Square} loading={ending} onclick={end}>End run</Button>
		{/if}
		{#if run}
			<Button loading={runBusy} onclick={toggleRun}>
				{run.excluded ? 'Include run' : 'Exclude run'}
			</Button>
		{/if}
	{/snippet}
	{#if run}
		<div class="flex flex-col gap-1">
			<div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink">
				<RunColors colors={run.colors} />
				{#if run.ended_at === null}<Badge tone="success" dot>Collecting</Badge>{/if}
				{#if run.excluded}<Badge>Excluded</Badge>{/if}
			</div>
			<p class="num text-sm text-ink-muted">
				{formatWhen(run.started_at)} to
				{#if run.ended_at === null}now{:else}{formatTime(run.ended_at)}, {formatDuration(
						run.ended_at - run.started_at
					)}{/if}.
				{run.segments.length}
				{run.segments.length === 1 ? 'segment' : 'segments'}, {run.pieces.toLocaleString()} pieces,
				{run.labeled.toLocaleString()} labeled, {run.excluded_pieces.toLocaleString()} excluded.
			</p>
		</div>
	{/if}
</PageHeader>

<Panel title="Pieces" flush>
	<div class="flex flex-col gap-3 px-(--pad-panel) pb-3">
		<SegmentedControl bind:value={filter} options={FILTERS} label="Which pieces" size="sm" />
		{#if error}<p class="text-sm text-danger-ink">{error}</p>{/if}
		{#if loading && pieces.length === 0}
			<p class="flex items-center gap-2 text-sm text-ink-muted">
				<Spinner size={14} /> Loading the pieces
			</p>
		{:else if pieces.length === 0 && !error}
			<p class="text-sm text-ink-muted">{EMPTY[filter]}</p>
		{/if}
	</div>
	{#if pieces.length > 0 && run}
		<div
			class="border-t border-line"
			role="group"
			aria-label="The run's pieces"
			onpointerenter={() => (held = true)}
			onpointerleave={() => (held = false)}
		>
			<PieceFeed
				{pieces}
				segments={run.segments}
				{base}
				pad="px-(--pad-panel)"
				ontoggle={togglePiece}
			/>
		</div>
		<div class="flex items-center justify-between gap-3 border-t border-line px-(--pad-panel) py-3">
			<span class="num text-sm text-ink-muted">
				{pieces.length.toLocaleString()} of {total.toLocaleString()}
			</span>
			{#if pieces.length < total}
				<Button size="sm" loading={loadingMore} onclick={loadMore}>Load more</Button>
			{/if}
		</div>
	{/if}
</Panel>
