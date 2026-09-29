<!--
	docs/surfaces.md. A panel is the surface plane: one job's worth of content
	on the canvas, told apart from it by fill, with no border and no shadow.
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
		actions,
		footer,
		children,
		class: className = ''
	}: {
		title?: string;
		description?: string;
		flush?: boolean;
		actions?: Snippet;
		footer?: Snippet;
		children: Snippet;
		class?: string;
	} = $props();
</script>

<section class="bg-surface {className}">
	{#if title || actions}
		<header class="flex items-start justify-between gap-4 px-5 pt-4 {flush ? 'pb-3' : 'pb-4'}">
			<div class="min-w-0">
				{#if title}<h2 class="text-base font-semibold text-ink">{title}</h2>{/if}
				{#if description}<p class="mt-0.5 text-sm text-ink-muted">{description}</p>{/if}
			</div>
			{#if actions}<div class="flex shrink-0 items-center gap-2">{@render actions()}</div>{/if}
		</header>
	{/if}
	<div class={flush ? '' : title || actions ? 'px-5 pb-5' : 'p-5'}>
		{@render children()}
	</div>
	{#if footer}
		<footer class="flex items-center justify-end gap-2 border-t border-line px-5 py-3">
			{@render footer()}
		</footer>
	{/if}
</section>
