<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title = '',
		description = '',
		children
	}: {
		title?: string;
		description?: string;
		children: Snippet;
	} = $props();
</script>

<section class="overflow-hidden border border-border">
	{#if title}
		<div class="border-b border-border bg-surface px-4 py-3">
			<h2 class="text-base font-semibold text-text">{title}</h2>
			{#if description}
				<p class="mt-1 text-sm text-text-muted">{description}</p>
			{/if}
		</div>
	{/if}
	<div class="p-4">
		{@render children()}
	</div>
</section>
