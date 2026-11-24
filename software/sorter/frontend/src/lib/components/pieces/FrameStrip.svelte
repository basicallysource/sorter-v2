<script lang="ts">
	import FrameTile from './FrameTile.svelte';
	import type { Frame } from './types';

	// Pictures of a piece in a grid of tiles whose columns and rows are given,
	// never counted from the pictures: three pictures or thirty take the same
	// place. What does not fit is a number in the last tile. Room for a tile's
	// stroke is the strip's own (its padding), so nothing that holds a strip can
	// cut a stroke off.
	let {
		frames,
		size,
		cols,
		rows = 1,
		onZoom
	}: {
		frames: Frame[];
		// A tile's side, in rem.
		size: number;
		cols: number;
		rows?: number;
		// Opens the full-size viewer when a picture is clicked.
		onZoom?: (src: string, label: string) => void;
	} = $props();

	const places = $derived(cols * rows);
	const side = $derived(`calc(${size}rem * var(--tile-scale, 1))`);
	const shown = $derived(frames.length > places ? frames.slice(0, places - 1) : frames);
	const more = $derived(frames.length - shown.length);
</script>

<div
	class="grid shrink-0 gap-1.5 p-0.5"
	style:grid-template-columns="repeat({cols}, {side})"
	style:grid-template-rows="repeat({rows}, {side})"
>
	{#each shown as frame (frame.key)}
		<FrameTile {frame} {size} {onZoom} />
	{/each}
	{#if more > 0}
		<span
			class="num flex items-center justify-center bg-well text-xs text-ink-muted"
			title="{more} more pictures, on the piece's page"
		>
			+{more}
		</span>
	{/if}
</div>
