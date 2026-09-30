<!--
	docs/components.md#profiles. A part's picture, shown whole on whatever it
	sits on: no well behind it, no backdrop and no bars (it is contained, never
	cropped). With no picture, or one that fails to load, a quiet blank square
	takes its place: never a broken-image or image-off icon. `class` gives it
	its size (`size-12`, or `aspect-square w-full` in a grid of tiles).
-->
<script lang="ts">
	let { src = null, class: className = '' }: { src?: string | null; class?: string } = $props();

	// The address that failed, so a new address gets its own try.
	let failed = $state<string | null>(null);
	let img = $state<HTMLImageElement | null>(null);
	const shown = $derived(src && failed !== src ? src : null);

	// A picture that failed before the page took over (server rendering) never
	// raises an error event here, so ask the element.
	$effect(() => {
		if (img && img.complete && img.naturalWidth === 0) failed = src;
	});
</script>

{#if shown}
	<img
		bind:this={img}
		src={shown}
		alt=""
		loading="lazy"
		decoding="async"
		onerror={() => (failed = shown)}
		class="block object-contain {className}"
	/>
{:else}
	<span aria-hidden="true" class="block rounded-control bg-hover {className}"></span>
{/if}
