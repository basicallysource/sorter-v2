<!--
	docs/surfaces.md. A panel is the surface plane: one job's worth of content
	on the canvas, told apart from it by fill, with no border and no shadow.
	Its corners are rounded-panel, and what runs to its edges is clipped to them.
	Panels never nest. A group inside a panel is a section of it (a heading,
	or a row in a divided list), and an inset area is a well (`bg-well`).

	`flush` drops the body's padding, for a divided list, a table or a picture
	that runs to the panel's edges.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		description,
		flush = false,
		fill = false,
		actions,
		footer,
		children,
		class: className = ''
	}: {
		title?: string;
		description?: string;
		flush?: boolean;
		// Take the height the layout gives it; the body scrolls inside
		// (docs/layout.md: an app screen fits the window).
		fill?: boolean;
		actions?: Snippet;
		footer?: Snippet;
		children: Snippet;
		class?: string;
	} = $props();
</script>

<section
	class="overflow-hidden rounded-panel bg-surface {fill ? 'flex min-h-0 flex-col' : ''} {className}"
>
	{#if title || actions}
		<header
			class="flex shrink-0 items-start justify-between gap-4 px-(--pad-panel) pt-4 {flush
				? 'pb-3'
				: 'pb-4'}"
		>
			<div class="min-w-0">
				{#if title}<h2 class="text-base font-semibold text-ink">{title}</h2>{/if}
				{#if description}<p class="mt-0.5 text-sm text-ink-muted">{description}</p>{/if}
			</div>
			{#if actions}<div class="flex shrink-0 items-center gap-2">{@render actions()}</div>{/if}
		</header>
	{/if}
	<div
		class="{flush
			? ''
			: title || actions
				? 'px-(--pad-panel) pb-(--pad-panel)'
				: 'p-(--pad-panel)'} {fill ? 'min-h-0 flex-1 overflow-y-auto' : ''}"
	>
		{@render children()}
	</div>
	{#if footer}
		<footer
			class="flex shrink-0 items-center justify-end gap-2 border-t border-line px-(--pad-panel) py-3"
		>
			{@render footer()}
		</footer>
	{/if}
</section>
