<!--
	The dashboard's Training data section, in place of Recent pieces while
	training mode is on. With no colors chosen it asks for one; with colors and
	no run it says what the next run will be; while a run collects it shows
	the run's latest pieces, each excluded or brought back with a click. A
	fixed bin, when one is set, is named first in every state. The
	pieces hold still while the pointer is over them, so a click lands on the
	piece that was aimed at.
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
	import RunColors from './RunColors.svelte';
	import TrainingColors from './TrainingColors.svelte';
	import TrainingPieceTile from './TrainingPieceTile.svelte';

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
	const LATEST = 12;

	const config = $derived(training.config);
	const run = $derived(training.current_run);
	const runId = $derived(training.current_run?.id ?? null);
	const lastRun = $derived(training.runs.find((r) => !r.collecting) ?? null);
	const fixedBin = $derived(training.config.bin);
	const fixedBinKey = $derived(fixedBin ? binKey(fixedBin) : null);
	// The bin's categories come from the bin layout, fetched when it changes.
	let bins = $state<BinChoice[]>([]);

	let editing = $state(false);
	let pieces = $state<TrainingPiece[]>([]);
	let error = $state<string | null>(null);

	// While the pointer is over the pieces, what a poll brings waits here.
	let held = false;
	let pending: TrainingPiece[] | null = null;

	function show(next: TrainingPiece[]) {
		if (held) pending = next;
		else pieces = next;
	}

	function release() {
		held = false;
		if (pending) pieces = pending;
		pending = null;
	}

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

	// The open run's latest pieces, every few seconds while it collects.
	$effect(() => {
		const id = runId;
		const from = base;
		pieces = [];
		pending = null;
		error = null;
		if (!id) return;
		editing = false;
		let stopped = false;
		const load = async () => {
			try {
				const res = await getRunPieces(from, id, { limit: LATEST });
				if (!stopped) show(res.pieces);
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
			const swap = (list: TrainingPiece[]) => list.map((p) => (p.uuid === next.uuid ? next : p));
			pieces = swap(pieces);
			if (pending) pending = swap(pending);
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		}
	}
</script>

<div class="h-full overflow-y-auto">
	<div class="flex flex-col gap-3 px-3 pt-1 pb-3">
		{#if fixedBin}
			<p class="text-sm text-ink">
				<span class="font-medium">All pieces to:</span>
				{binLabel(fixedBin, bins)}
			</p>
		{/if}
		{#if config.color_ids.length === 0}
			<p class="text-sm text-ink">Pick the color you're feeding.</p>
			<TrainingColors {base} {training} onsaved={onchange} />
		{:else if run}
			<div class="flex flex-col gap-1">
				<p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink">
					<span class="font-medium">Collecting:</span>
					<RunColors colors={run.colors} />
				</p>
				<p class="text-sm text-ink-muted">
					<span class="num">{run.pieces.toLocaleString()}</span>
					{run.pieces === 1 ? 'piece' : 'pieces'} since
					<span class="num">{formatTime(run.started_at)}</span>. Click a piece to exclude it.
				</p>
			</div>
			{#if pieces.length > 0}
				<div
					class="grid gap-x-3 gap-y-4"
					role="group"
					aria-label="The run's pieces"
					style:grid-template-columns="repeat(auto-fill, minmax(6rem, 1fr))"
					onpointerenter={() => (held = true)}
					onpointerleave={release}
				>
					{#each pieces as piece (piece.uuid)}
						<TrainingPieceTile {piece} {base} ontoggle={toggle} />
					{/each}
				</div>
			{:else}
				<p class="text-sm text-ink-muted">No pieces yet.</p>
			{/if}
			{#if error}<p class="text-sm text-danger-ink">{error}</p>{/if}
			<div class="flex flex-wrap gap-2">
				<Button size="sm" href="/settings/training-data/{run.id}">This run</Button>
				<Button size="sm" variant="ghost" href="/settings/training-data">All runs</Button>
			</div>
		{:else if editing}
			<p class="text-sm text-ink">The colors for the next run:</p>
			<TrainingColors {base} {training} onsaved={onchange} />
			<div>
				<Button size="sm" onclick={() => (editing = false)}>Done</Button>
			</div>
		{:else}
			<div class="flex flex-col gap-1">
				<p class="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-ink">
					<span class="font-medium">Next run:</span>
					<RunColors colors={config.colors} />
				</p>
				<p class="text-sm text-ink-muted">It starts when the machine runs.</p>
			</div>
			<div>
				<Button size="sm" onclick={() => (editing = true)}>Change colors</Button>
			</div>
			{#if lastRun}
				<p class="text-sm text-ink-muted">
					Last run:
					<a href="/settings/training-data/{lastRun.id}" class="text-primary-ink hover:underline">
						<span class="num">{lastRun.pieces.toLocaleString()}</span>
						{lastRun.pieces === 1 ? 'piece' : 'pieces'},
						<span class="num">{lastRun.excluded_pieces.toLocaleString()}</span> excluded
					</a>
				</p>
			{/if}
		{/if}
	</div>
</div>
