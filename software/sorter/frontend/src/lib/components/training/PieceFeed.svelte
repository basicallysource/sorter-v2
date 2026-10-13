<!--
	A run's pieces as rows, newest first, with a divider wherever the segment
	changes: the segment's colors, its piece count and when it ran. `lead`
	puts the open segment's divider on top even before it has a piece, so a
	new color shows the moment it is chosen.
-->
<script lang="ts">
	import { formatTime, type TrainingPiece, type TrainingSegment } from '$lib/training/api';
	import RunColors from './RunColors.svelte';
	import TrainingPieceRow from './TrainingPieceRow.svelte';

	let {
		pieces,
		segments,
		base,
		lead = false,
		pad = 'px-3',
		ontoggle
	}: {
		pieces: TrainingPiece[];
		segments: TrainingSegment[];
		base: string;
		lead?: boolean;
		pad?: string;
		ontoggle: (piece: TrainingPiece) => void;
	} = $props();

	type Item =
		| { kind: 'segment'; key: string; segment: TrainingSegment | null }
		| { kind: 'piece'; key: string; piece: TrainingPiece };

	const items = $derived.by(() => {
		const byId = new Map(segments.map((s) => [s.id, s]));
		const out: Item[] = [];
		let current: string | null | undefined = undefined;
		const open = segments[segments.length - 1];
		if (lead && open && open.ended_at === null && pieces[0]?.segment_id !== open.id) {
			out.push({ kind: 'segment', key: `segment-${open.id}-lead`, segment: open });
			current = open.id;
		}
		for (const piece of pieces) {
			const id = piece.segment_id ?? null;
			if (id !== current) {
				const segment = id ? (byId.get(id) ?? null) : null;
				out.push({ kind: 'segment', key: `segment-${id}-${out.length}`, segment });
				current = id;
			}
			out.push({ kind: 'piece', key: piece.uuid, piece });
		}
		return out;
	});
</script>

<div class="divide-y divide-line">
	{#each items as item (item.key)}
		{#if item.kind === 'segment'}
			<div class="flex flex-wrap items-center gap-x-3 gap-y-1 bg-well {pad} py-1.5 text-sm">
				{#if item.segment}
					<RunColors colors={item.segment.colors} class="font-medium text-ink" />
					<span class="num text-ink-muted">
						{item.segment.pieces.toLocaleString()}
						{item.segment.pieces === 1 ? 'piece' : 'pieces'}
					</span>
					<span class="num text-ink-muted">
						from {formatTime(item.segment.started_at)}{#if item.segment.ended_at !== null}
							to {formatTime(item.segment.ended_at)}{/if}
					</span>
				{:else}
					<span class="text-ink-muted">Outside a segment</span>
				{/if}
			</div>
		{:else}
			<TrainingPieceRow piece={item.piece} {base} {pad} {ontoggle} />
		{/if}
	{/each}
</div>
