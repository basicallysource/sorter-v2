<script lang="ts">
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import PartImage from '$lib/components/ui/PartImage.svelte';
	import Lane from './Lane.svelte';
	import ReviewPreview from './ReviewPreview.svelte';
	import RowFacts from './RowFacts.svelte';
	import { RIDE, shotsOf, type Channel, type PieceView } from './model';

	// A row of the records, laid out as the piece's ride through the machine:
	// what C2 saw, what C3 saw, what the classification channel saw, and what
	// came of it. Each channel has a block of slots that is always the same
	// size, so the blocks line up down the list.
	let { piece }: { piece: PieceView } = $props();

	const COLS: Record<Channel, number> = { C2: 2, C3: 4, C4: 3 };
</script>

<div class="@container px-(--pad-panel) py-3">
	<div
		class="grid grid-cols-[minmax(0,1fr)] items-center gap-x-5 gap-y-3 @3xl:grid-cols-[auto_minmax(0,1fr)] @6xl:grid-cols-[auto_minmax(0,1fr)_24rem]"
	>
		<div class="flex h-[6.375rem] flex-wrap content-start items-end gap-x-3 overflow-hidden">
			{#each RIDE as channel (channel)}
				{@const shots = shotsOf(piece, channel)}
				<div class="flex h-full shrink-0 flex-col justify-end gap-1">
					<span class="flex items-baseline gap-1.5 text-xs">
						<span class="font-mono text-ink-muted">{channel}</span>
						<span class="num text-ink-faint">{shots.length || 'none'}</span>
					</span>
					<Lane {shots} size={2.25} cols={COLS[channel]} rows={2} />
				</div>
			{/each}
			<span class="flex h-[4.875rem] shrink-0 items-center text-ink-faint">
				<ArrowRight size={16} />
			</span>
			<ImageZoom src={piece.reference} label="Brickognize's picture of this part" class="shrink-0">
				<PartImage src={piece.reference} class="size-[4.875rem]" />
			</ImageZoom>
		</div>

		<RowFacts {piece} />

		<div class="@3xl:col-span-2 @6xl:col-span-1">
			<ReviewPreview {piece} layout="compact" />
		</div>
	</div>
</div>
