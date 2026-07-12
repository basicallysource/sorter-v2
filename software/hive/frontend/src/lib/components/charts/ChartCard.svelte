<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		subtitle = '',
		children
	}: {
		title: string;
		subtitle?: string;
		children: Snippet;
	} = $props();
</script>

<div class="border border-border bg-surface">
	<div class="border-b border-border bg-bg px-4 py-2">
		<h3 class="text-sm font-semibold text-text">{title}</h3>
		{#if subtitle}<p class="text-xs text-text-muted">{subtitle}</p>{/if}
	</div>
	<div class="p-3">{@render children()}</div>
</div>
