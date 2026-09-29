<!-- A titled part of a site page: a heading on the canvas, then its specimens. -->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let { title, lead, children }: { title: string; lead?: string; children: Snippet } = $props();
	const id = $derived(title.toLowerCase().replace(/[^a-z0-9]+/g, '-'));
</script>

<section {id} class="mt-12 scroll-mt-16 first:mt-0">
	<h2 class="text-xl font-semibold tracking-tight text-ink">{title}</h2>
	{#if lead}<p class="mt-1 max-w-2xl text-sm text-ink-muted">{lead}</p>{/if}
	<div class="mt-4 flex flex-col gap-4">{@render children()}</div>
</section>
