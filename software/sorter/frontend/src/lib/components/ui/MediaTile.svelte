<!--
	docs/components.md#panels. A camera feed or a photo: a strip on the
	surface with its name and its controls, then the picture on the media
	backdrop, which is dark in both modes. Anything drawn over the picture
	sits in a dark subtree, so it reads on the backdrop whatever the page's
	mode.

	The picture's box is the picture's own shape, so the tile hugs its picture
	and never shows a bar above and below it or down its sides. `aspect` (a CSS
	ratio, "16 / 9") is that shape until the picture has loaded; then the
	natural size of the <img> or <video> inside takes over, whatever the camera
	sends. A layout gives a tile a width and lets its height follow; it never
	gives a tile a height the picture would not fill (docs/layout.md, the
	dashboard layout).

	`header={false}` drops the strip, for a picture that is the whole tile:
	the name only names it for a screen reader, and `actions` go over the
	picture with `overlay`, on the scrim so they read on any picture.

	`expandable` adds a full screen button. Full screen, the tile itself fills
	the window on the media plane (the browser's top layer), so a live feed
	is never loaded twice; its button becomes "Exit full screen", and Escape
	leaves too. `bind:expanded` drives it from code. Full screen is the one
	place a picture has bars: the window has its own shape.
-->
<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import Maximize from '@lucide/svelte/icons/maximize-2';
	import Minimize from '@lucide/svelte/icons/minimize-2';
	import Button from './Button.svelte';

	let {
		title,
		header = true,
		actions,
		children,
		overlay,
		expandable = false,
		expanded = $bindable(false),
		aspect = '16 / 9',
		class: className = ''
	}: {
		title: string;
		// False for an overlay-only tile: no strip above the picture.
		header?: boolean;
		actions?: Snippet;
		// The picture, or what stands in for it.
		children: Snippet;
		// Chips or controls over the picture, in its top right corner.
		overlay?: Snippet;
		expandable?: boolean;
		expanded?: boolean;
		// The picture's shape as a CSS ratio, until it loads and reports its own.
		aspect?: string;
		class?: string;
	} = $props();

	let tile: HTMLElement;
	// The picture's own shape once an <img> or <video> inside has loaded.
	let natural = $state<string | null>(null);
	// The tile's height, held in the page while it is full screen, so
	// nothing under it moves and the scroll stays where it was.
	let held = $state(0);

	$effect(() => {
		if (expanded && !tile.matches(':popover-open')) tile.showPopover();
	});

	function measure(event: Event) {
		const el = event.target;
		const [width, height] =
			el instanceof HTMLImageElement
				? [el.naturalWidth, el.naturalHeight]
				: el instanceof HTMLVideoElement
					? [el.videoWidth, el.videoHeight]
					: [0, 0];
		if (width > 0 && height > 0) natural = `${width} / ${height}`;
	}

	function toggle() {
		if (expanded) return tile.hidePopover();
		held = tile.offsetHeight;
		expanded = true;
	}

	function ontoggle(event: ToggleEvent) {
		expanded = event.newState === 'open';
		// The button pressed was swapped for its opposite; focus goes to that
		// one, unless something else (a dialog) has taken it meanwhile.
		tick().then(() => {
			const at = document.activeElement;
			if (at === document.body || tile.contains(at)) {
				tile.querySelector<HTMLElement>('[data-expand]')?.focus();
			}
		});
	}
</script>

{#snippet expand()}
	{#if expanded}
		<Button size="sm" variant="secondary" icon={Minimize} onclick={toggle} data-expand
			>Exit full screen</Button
		>
	{:else}
		<Button
			size="sm"
			variant="ghost"
			icon={Maximize}
			label="Full screen"
			onclick={toggle}
			data-expand
		/>
	{/if}
{/snippet}

{#if expanded && held}
	<div class={className} style:height="{held}px" aria-hidden="true"></div>
{/if}

<section
	bind:this={tile}
	popover={expanded ? 'auto' : undefined}
	{ontoggle}
	aria-label={header ? undefined : title}
	class="flex min-h-0 flex-col overflow-hidden {expanded
		? 'dark fixed inset-0 m-0 h-auto max-h-none w-auto max-w-none border-0 bg-media p-0 text-ink'
		: `rounded-panel bg-surface ${className}`}"
>
	{#if header}
		<header
			class="flex h-(--size-control-lg) shrink-0 items-center justify-between gap-3 pr-2 pl-(--pad-panel)"
		>
			<h3 class="truncate text-sm font-medium text-ink">{title}</h3>
			{#if actions || expandable}
				<div class="flex shrink-0 items-center gap-1">
					{#if actions}{@render actions()}{/if}
					{#if expandable}{@render expand()}{/if}
				</div>
			{/if}
		</header>
	{/if}
	<div
		class="dark relative flex items-center justify-center overflow-hidden bg-media {expanded
			? 'min-h-0 flex-1'
			: 'aspect-(--aspect)'}"
		style:--aspect={natural ?? aspect}
		onloadcapture={measure}
		onloadedmetadatacapture={measure}
	>
		{@render children()}
		{#if overlay || (!header && (actions || expandable))}
			<div class="absolute top-2 right-2 flex items-center gap-1.5">
				{#if overlay}{@render overlay()}{/if}
				{#if !header && (actions || expandable)}
					<div class="flex items-center gap-1 rounded-button bg-scrim">
						{#if actions}{@render actions()}{/if}
						{#if expandable}{@render expand()}{/if}
					</div>
				{/if}
			</div>
		{/if}
	</div>
</section>
