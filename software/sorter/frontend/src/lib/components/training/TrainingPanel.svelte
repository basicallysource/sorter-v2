<!--
	The dashboard's Training data section, in place of Recent pieces while
	training mode is on. A bar that stays at the top: the color being fed (a
	pick saves at once and, mid-run, starts a new segment), the run's state,
	Start run or End run, and All runs. Under it the fixed bin, when one is
	set. Then the open run's pieces as a live feed of rows, newest first, with
	a divider for each segment; a click excludes a piece or brings it back.
	With no run open, the last run in one line.
-->
<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import { fetchLegoColors } from '$lib/pieces/colors';
	import {
		binKey,
		binLabel,
		formatTime,
		getBinChoices,
		getRunPieces,
		setPieceExcluded,
		type BinChoice,
		type TrainingPiece,
		type TrainingState
	} from '$lib/training/api';
	import ColorDropdown from './ColorDropdown.svelte';
	import PieceFeed from './PieceFeed.svelte';
	import RunButton from './RunButton.svelte';

	let {
		base,
		training,
		onchange
	}: {
		base: string;
		training: TrainingState;
		onchange: (next: TrainingState) => void;
	} = $props();

	const POLL_MS = 3000;
	const FEED = 100;

	const run = $derived(training.current_run);
	const runId = $derived(training.current_run?.id ?? null);
	const lastRun = $derived(training.runs.find((r) => !r.collecting) ?? null);
	const fixedBin = $derived(training.config.bin);
	const fixedBinKey = $derived(fixedBin ? binKey(fixedBin) : null);

	let pieces = $state<TrainingPiece[]>([]);
	let error = $state<string | null>(null);
	// The bin's categories come from the bin layout, fetched when it changes.
	let bins = $state<BinChoice[]>([]);

	// The swatches on the pieces come from the machine's palette.
	$effect(() => {
		fetchLegoColors(base).catch(() => {});
	});

	$effect(() => {
		const from = base;
		if (!fixedBinKey) return;
		getBinChoices(from)
			.then((choices) => {
				if (from === base) bins = choices;
			})
			.catch(() => {});
	});

	// The open run's newest pieces, every few seconds.
	$effect(() => {
		const id = runId;
		const from = base;
		pieces = [];
		error = null;
		if (!id) return;
		let stopped = false;
		const load = async () => {
			try {
				const res = await getRunPieces(from, id, { limit: FEED });
				if (!stopped) pieces = res.pieces;
			} catch {
				// keep what is shown; the next poll tries again
			}
		};
		void load();
		const timer = setInterval(load, POLL_MS);
		return () => {
			stopped = true;
			clearInterval(timer);
		};
	});

	async function toggle(piece: TrainingPiece) {
		error = null;
		try {
			const next = await setPieceExcluded(base, piece.uuid, !piece.training_excluded);
			pieces = pieces.map((p) => (p.uuid === next.uuid ? next : p));
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}
</script>

<div class="flex h-full min-h-0 flex-col">
	<div
		class="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-3 pb-2.5"
	>
		<ColorDropdown {base} {training} onsaved={onchange} />
		<span class="min-w-0 flex-1 text-sm text-ink-muted">
			{#if run}
				Run: <span class="num text-ink">{run.pieces.toLocaleString()}</span>
				{run.pieces === 1 ? 'piece' : 'pieces'} since
				<span class="num">{formatTime(run.started_at)}</span>
			{:else}
				No run
			{/if}
		</span>
		<span class="flex items-start gap-2">
			<RunButton {base} {training} {onchange} />
			<Button size="sm" variant="ghost" href="/settings/training-data">All runs</Button>
		</span>
	</div>

	{#if fixedBin}
		<p class="shrink-0 truncate border-b border-line px-3 py-1.5 text-sm text-ink-muted">
			All pieces to: <span class="text-ink">{binLabel(fixedBin, bins)}</span>
		</p>
	{/if}
	{#if error}
		<p class="shrink-0 border-b border-line px-3 py-1.5 text-sm text-danger-ink">{error}</p>
	{/if}

	<div class="min-h-0 flex-1 overflow-y-auto">
		{#if run}
			{#if pieces.length > 0 || run.segments.length > 0}
				<PieceFeed {pieces} segments={run.segments} {base} lead ontoggle={toggle} />
			{/if}
			{#if pieces.length === 0}
				<p class="px-3 py-2.5 text-sm text-ink-muted">No pieces yet.</p>
			{/if}
		{:else if lastRun}
			<p class="px-3 py-2.5 text-sm text-ink-muted">
				Last run:
				<a href="/settings/training-data/{lastRun.id}" class="text-primary-ink hover:underline">
					<span class="num">{lastRun.pieces.toLocaleString()}</span>
					{lastRun.pieces === 1 ? 'piece' : 'pieces'},
					<span class="num">{lastRun.excluded_pieces.toLocaleString()}</span> excluded, from
					<span class="num">{formatTime(lastRun.started_at)}</span>
				</a>
			</p>
		{/if}
	</div>
</div>
