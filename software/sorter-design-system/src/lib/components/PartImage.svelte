<!--
	docs/components.md#profiles. A part's picture, shown whole on whatever it
	sits on: no well behind it, no backdrop and no bars (it is contained, never
	cropped). With no picture, or one that fails to load, a quiet blank square
	takes its place: never a broken-image or image-off icon. `fallback` is a
	second picture to try when the first fails (a part rendered in a bin's
	color may have no render; its photo is the fallback). `class` gives it its
	size (`size-12`, or `aspect-square w-full` in a grid of tiles).

	With `onzoom` the picture can be seen up close: the pointer turns to a
	magnifier over it, a magnifier shows in its corner, and a click (or Enter
	on it) calls `onzoom` with the picture shown, for the app to open in a
	`Lightbox`. Inside a link it is the link's job instead: put the zoom button
	beside the link, never in it.
-->
<script lang="ts">
	import ZoomIn from '@lucide/svelte/icons/zoom-in';

	let {
		src = null,
		fallback = null,
		onzoom,
		class: className = ''
	}: {
		src?: string | null;
		fallback?: string | null;
		onzoom?: (src: string) => void;
		class?: string;
	} = $props();

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

{#if shown && onzoom}
	<button
		type="button"
		aria-label="See the picture up close"
		onclick={(event) => {
			event.preventDefault();
			event.stopPropagation();
			onzoom(shown);
		}}
		class="group/zoom relative block cursor-zoom-in rounded-control {className}"
	>
		<img
			bind:this={img}
			src={shown}
			alt=""
			loading="lazy"
			decoding="async"
			onerror={fail}
			class="block size-full object-contain"
		/>
		<span
			aria-hidden="true"
			class="absolute top-1 left-1 flex size-7 items-center justify-center rounded-button bg-surface text-ink opacity-0 ring-1 ring-line transition-opacity group-hover/zoom:opacity-100 group-focus-visible/zoom:opacity-100"
		>
			<ZoomIn size={14} />
		</span>
	</button>
{:else if shown}
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
