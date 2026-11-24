<script lang="ts">
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import type { Frame } from './types';

	// One picture of a piece, whole, on a quiet square tile of a fixed size. The
	// tile never takes its size from the picture, so a row of them is the same
	// row whatever shapes the pictures have. A picture that produced the result
	// has a stroke around its tile, with square corners. Under the pointer the
	// picture is enlarged (ImageZoom), and what is said about it there includes
	// how sharp it is; nothing is written on the tile.
	let {
		frame,
		size,
		mark = true,
		onZoom
	}: {
		frame: Frame;
		// The tile's side, in rem. What holds the tile can scale every tile in
		// it with --tile-scale (a narrower row, smaller tiles).
		size: number;
		// Whether a picture that produced the result gets its stroke.
		mark?: boolean;
		// Opens the full-size viewer when the picture is clicked. Without it the
		// tile is not a button.
		onZoom?: (src: string, label: string) => void;
	} = $props();

	let failed = $state(false);

	const label = $derived(
		frame.sharpness ? `${frame.label} · sharpness ${frame.sharpness}` : frame.label
	);
	const side = $derived(`calc(${size}rem * var(--tile-scale, 1))`);
	const tile = $derived(
		`relative block shrink-0 overflow-hidden bg-well ${frame.used && mark ? 'outline-2 outline-primary' : ''}`
	);
</script>

{#snippet picture()}
	{#if !failed}
		<img
			src={frame.src}
			alt=""
			loading="lazy"
			decoding="async"
			onerror={() => (failed = true)}
			class="block size-full object-contain"
		/>
	{/if}
{/snippet}

<ImageZoom src={frame.src} {label} class="shrink-0">
	{#if onZoom}
		<button
			type="button"
			aria-label={label}
			class="{tile} cursor-pointer transition-colors hover:bg-hover"
			style:width={side}
			style:height={side}
			onclick={() => onZoom(frame.src, label)}
		>
			{@render picture()}
		</button>
	{:else}
		<span class={tile} style:width={side} style:height={side}>
			{@render picture()}
		</span>
	{/if}
</ImageZoom>
