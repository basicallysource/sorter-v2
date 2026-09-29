<!--
	docs/components.md#media-tile. A camera feed or a photo: a strip on the
	surface with its name and its controls, then the picture on the media
	backdrop, which is dark in both modes. Anything drawn over the picture
	sits in a dark subtree, so it reads on the backdrop whatever the page's
	mode. The picture keeps its aspect ratio; with `fill`, from lg up it takes
	the height the layout gives it instead (a dashboard that fits the window).
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		actions,
		children,
		overlay,
		fill = false,
		aspect = '16 / 9',
		class: className = ''
	}: {
		title: string;
		actions?: Snippet;
		// The picture, or what stands in for it.
		children: Snippet;
		// Chips or controls over the picture, in its top right corner.
		overlay?: Snippet;
		fill?: boolean;
		aspect?: string;
		class?: string;
	} = $props();
</script>

<section
	class="flex min-h-0 flex-col overflow-hidden rounded-panel bg-surface {fill
		? 'lg:h-full'
		: ''} {className}"
>
	<header
		class="flex h-(--size-control-lg) shrink-0 items-center justify-between gap-3 pr-2 pl-(--pad-panel)"
	>
		<h3 class="truncate text-sm font-medium text-ink">{title}</h3>
		{#if actions}<div class="flex shrink-0 items-center gap-1">{@render actions()}</div>{/if}
	</header>
	<div
		class="dark relative flex items-center justify-center overflow-hidden bg-media {fill
			? 'aspect-(--aspect) lg:aspect-auto lg:min-h-0 lg:flex-1'
			: 'aspect-(--aspect)'}"
		style:--aspect={aspect}
	>
		{@render children()}
		{#if overlay}<div class="absolute top-2 right-2 flex items-center gap-1.5">
				{@render overlay()}
			</div>{/if}
	</div>
</section>
