<script lang="ts">
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import { pictures, type Fit } from './fit.svelte';
	import type { Shot } from './model';

	// One picture of a piece in a slot of a fixed size. The slot never takes its
	// size from the picture, so a row of them is the same row whatever shapes
	// the pictures have and however many there are. A picture that produced the
	// result has a stroke around its slot. Under the pointer it is shown whole
	// and large, with what is known about it.
	let {
		shot,
		size,
		fit,
		mark = true,
		selected = false,
		onpick
	}: {
		shot: Shot;
		// The slot's side, in rem. A layout scales every slot inside it with
		// --slot-scale (a narrower row, smaller slots).
		size: number;
		// This slot's own way, when it is not the page's.
		fit?: Fit;
		// Whether a picture that produced the result gets its stroke.
		mark?: boolean;
		selected?: boolean;
		// Makes it a button: the picture was chosen.
		onpick?: () => void;
	} = $props();

	const how = $derived(fit ?? pictures.fit);
	const side = $derived(`calc(${size}rem * var(--slot-scale, 1))`);
	const box = $derived(
		[
			'relative block shrink-0 overflow-hidden rounded-item',
			how === 'tile' ? 'bg-well' : '',
			shot.used && mark
				? `outline-primary ${selected ? 'outline-[3px]' : 'outline-2'}`
				: selected
					? 'outline-2 outline-ink'
					: ''
		].join(' ')
	);
</script>

{#snippet picture()}
	<img
		src={shot.src}
		alt=""
		loading="lazy"
		decoding="async"
		class="block size-full {how === 'fill' ? 'object-cover' : 'object-contain'}"
	/>
{/snippet}

<ImageZoom src={shot.src} label={shot.label} class="shrink-0">
	{#if onpick}
		<button
			type="button"
			aria-label={shot.label}
			aria-pressed={selected}
			class="{box} cursor-pointer"
			style:width={side}
			style:height={side}
			onclick={onpick}
		>
			{@render picture()}
		</button>
	{:else}
		<span class={box} style:width={side} style:height={side}>
			{@render picture()}
		</span>
	{/if}
</ImageZoom>
