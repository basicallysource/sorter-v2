<!--
	The card on a bin's front in the 3D view: the bin's number and what it
	takes, as the Bins page shows them, over the last pieces that went in. It
	is laid out at the view's CARD_SIZE and the view turns it onto the bin, so
	every card is one size. State is a fill, as everywhere: the chosen bin
	takes the primary's tint, the bin the chute points at the success tint,
	and the pointer over it lays the hover fill on top.
-->
<script module lang="ts">
	/** How many of the last pieces a card shows. */
	export const PIECES = 4;
</script>

<script lang="ts">
	import PieceThumb from '$lib/components/PieceThumb.svelte';
	import { pieceTooltip, previewUrl } from '$lib/components/bins/pieces';
	import type { BinContentItem } from '$lib/components/bins/types';

	let {
		number,
		name,
		pieces,
		chosen = false,
		current = false,
		hovered = false,
		off = false
	}: {
		number: number;
		// What the bin takes; empty when nothing is assigned.
		name: string;
		// The last pieces in, newest first; one tile each, up to PIECES.
		pieces: BinContentItem[];
		chosen?: boolean;
		current?: boolean;
		hovered?: boolean;
		// Its layer or section is off, or the chute cannot reach it.
		off?: boolean;
	} = $props();

	const tint = $derived(
		chosen
			? 'bg-primary-soft text-primary-ink'
			: current
				? 'bg-success-soft text-success-ink'
				: 'bg-surface text-ink'
	);
</script>

<div
	class="relative flex h-full w-full flex-col gap-1.5 overflow-hidden rounded-panel p-2 {tint} {off
		? 'opacity-60'
		: ''}"
>
	{#if hovered}<span class="absolute inset-0 bg-hover"></span>{/if}
	<div class="relative flex min-w-0 items-center gap-1.5">
		<span
			class="num shrink-0 rounded-badge bg-hover px-1.5 text-xs leading-5 font-medium {chosen ||
			current
				? ''
				: 'text-ink-muted'}">{number}</span
		>
		<span class="truncate text-sm leading-5 {name ? 'font-medium' : 'text-ink-muted'}">
			{name || 'Unassigned'}
		</span>
	</div>
	<div class="relative grid grid-cols-4 gap-1.5">
		{#each { length: PIECES } as _, i (i)}
			{@const piece = pieces[i]}
			<div class="aspect-square overflow-hidden rounded-item bg-surface">
				{#if piece}
					<PieceThumb
						src={previewUrl(piece)}
						alt={pieceTooltip(piece)}
						fallbackText={piece.part_id ?? '?'}
					/>
				{/if}
			</div>
		{/each}
	</div>
</div>
