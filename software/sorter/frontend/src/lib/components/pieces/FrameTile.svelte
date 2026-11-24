<script lang="ts">
	import ImageZoom from '$lib/components/ui/ImageZoom.svelte';
	import type { Frame } from './types';

	// One picture of a piece in a FrameStrip. It is shown whole in a square
	// place, at its own shape, so the stroke around a picture that produced the
	// result runs around the picture itself and never around bars beside it.
	// Under the pointer it is enlarged (ImageZoom), and what is said about it
	// there includes how sharp it is; nothing but the channel is written on it.
	let {
		frame,
		size,
		onZoom
	}: {
		frame: Frame;
		size: 'sm' | 'md';
		// Opens the full-size viewer when the picture is clicked. Without it the
		// picture is not a button (the records list wraps a whole row in a link).
		onZoom?: (src: string, label: string) => void;
	} = $props();

	let width = $state(0);
	let height = $state(0);
	let failed = $state(false);

	const label = $derived(
		frame.sharpness ? `${frame.label} · sharpness ${frame.sharpness}` : frame.label
	);
	const place = $derived(size === 'sm' ? 'size-9' : 'size-[4.75rem] p-1');
</script>

{#snippet picture()}
	{#if failed}
		<span aria-hidden="true" class="block size-full rounded-item bg-hover"></span>
	{:else}
		<img
			src={frame.src}
			alt=""
			loading="lazy"
			decoding="async"
			bind:naturalWidth={width}
			bind:naturalHeight={height}
			onerror={() => (failed = true)}
			class="block max-h-full max-w-full object-contain {height > width
				? 'h-full w-auto'
				: 'h-auto w-full'} {frame.used ? 'outline-2 outline-primary' : ''}"
		/>
	{/if}
	{#if size === 'md'}
		<span
			class="dark absolute bottom-1 left-1 rounded-badge bg-scrim px-1 text-xs font-medium text-ink"
		>
			{frame.channel}
		</span>
	{/if}
{/snippet}

<ImageZoom src={frame.src} {label} class="shrink-0">
	{#if onZoom}
		<button
			type="button"
			aria-label={label}
			class="relative grid shrink-0 place-items-center rounded-item transition-colors hover:bg-hover {place}"
			onclick={() => onZoom(frame.src, label)}
		>
			{@render picture()}
		</button>
	{:else}
		<span class="relative grid shrink-0 place-items-center {place}">
			{@render picture()}
		</span>
	{/if}
</ImageZoom>
