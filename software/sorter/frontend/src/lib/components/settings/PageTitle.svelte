<script lang="ts">
	// A settings page's title, its sentence, and anything that belongs beside
	// the title (a badge such as "Experimental").
	import type { Snippet } from 'svelte';

	let {
		title,
		description,
		children
	}: { title: string; description?: string; children?: Snippet } = $props();
</script>

<div class="mb-2">
	<div class="flex flex-wrap items-center gap-2">
		<h1 class="text-xl font-semibold tracking-tight text-ink">{title}</h1>
		{#if children}{@render children()}{/if}
	</div>
	{#if description}<p class="mt-1 max-w-3xl text-sm text-ink-muted">{description}</p>{/if}
</div>
