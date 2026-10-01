<!--
	docs/components.md#profiles. A part's picture, shown whole on whatever it
	sits on: no well behind it, no backdrop and no bars (it is contained, never
	cropped). With no picture, or one that fails to load, a quiet blank square
	takes its place: never a broken-image or image-off icon. `fallback` is a
	second picture to try when the first fails (a part rendered in a bin's
	color may have no render; its photo is the fallback). `class` gives it its
	size (`size-12`, or `aspect-square w-full` in a grid of tiles).
-->
<script lang="ts">
	let {
		src = null,
		fallback = null,
		class: className = ''
	}: { src?: string | null; fallback?: string | null; class?: string } = $props();

	// The addresses that failed, so each gets one try and a new one its own.
	let failed = $state<string[]>([]);
	let img = $state<HTMLImageElement | null>(null);
	const shown = $derived([src, fallback].find((url) => url && !failed.includes(url)) ?? null);

	function fail() {
		if (shown && !failed.includes(shown)) failed = [...failed, shown];
	}

	// A picture that failed before the page took over (server rendering) never
	// raises an error event here, so ask the element.
	$effect(() => {
		if (img && img.complete && img.naturalWidth === 0) fail();
	});
</script>

{#if shown}
	<img
		bind:this={img}
		src={shown}
		alt=""
		loading="lazy"
		decoding="async"
		onerror={fail}
		class="block object-contain {className}"
	/>
{:else}
	<span aria-hidden="true" class="block rounded-control bg-hover {className}"></span>
{/if}
