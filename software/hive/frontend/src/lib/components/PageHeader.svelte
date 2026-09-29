<!--
	A page's title and one sentence on the canvas, with the page's own actions
	at the right, 16px above the first panel (the design system's
	docs/layout.md, "A page").
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		description,
		actions,
		children
	}: {
		title: string;
		description?: string;
		actions?: Snippet;
		// More under the sentence: a link back, a status.
		children?: Snippet;
	} = $props();
</script>

<header class="mb-(--gap-panels) flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
	<div class="min-w-0">
		<h1 class="text-xl font-semibold text-ink">{title}</h1>
		{#if description}<p class="mt-1 text-sm text-ink-muted">{description}</p>{/if}
		{#if children}{@render children()}{/if}
	</div>
	{#if actions}<div class="flex shrink-0 flex-wrap items-center gap-2">{@render actions()}</div>{/if}
</header>
