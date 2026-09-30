<!--
	The card on a bin's front in the 3D view: the bin's number and what it
	takes, as the Bins page shows them, over the last pieces that went in. It
	is laid out at CARD_SIZE (layout.ts), drawn at the zoom the view sets in
	--card-zoom, and turned onto the bin by the view, so every card is one
	size. State is a fill, as everywhere: the chosen bin takes the primary's
	tint, the bin the chute points at the success tint, and the pointer over
	it lays the hover fill on top.

	Nothing in it animates and its pictures load at once (no lazy loading, no
	skeleton, no fade): the browser draws each card once and keeps that picture
	while the view moves, and anything that changes on its own would make it
	draw the card again.
-->
<script module lang="ts">
	/** How many of the last pieces a card shows. */
	export const PIECES = 4;
</script>

<script lang="ts">
	import { previewUrl } from '$lib/components/bins/pieces';
	import type { BinContentItem } from '$lib/components/bins/types';
	import { CARD_SIZE } from '$lib/machine3d/layout';

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
	class="relative flex flex-col gap-1.5 overflow-hidden rounded-panel p-2 {tint} {off
		? 'opacity-60'
		: ''}"
	style:width="{CARD_SIZE.width}px"
	style:height="{CARD_SIZE.height}px"
	style:zoom="var(--card-zoom, 1)"
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
			{@const src = previewUrl(pieces[i] ?? null)}
			<div class="aspect-square overflow-hidden rounded-item bg-surface">
				{#if src}
					<img
						{src}
						alt=""
						class="h-full w-full object-contain"
						onerror={(e) => ((e.currentTarget as HTMLImageElement).style.visibility = 'hidden')}
					/>
				{/if}
			</div>
		{/each}
	</div>
</div>
