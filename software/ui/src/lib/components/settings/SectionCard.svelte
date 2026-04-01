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

<section class="dark:border-border-dark overflow-hidden border border-border">
	{#if title}
		<div class="dark:border-border-dark dark:bg-surface-dark border-b border-border bg-surface px-4 py-3">
			<h2 class="dark:text-text-dark text-base font-semibold text-text">{title}</h2>
			{#if description}
				<p class="dark:text-text-muted-dark mt-1 text-sm text-text-muted">{description}</p>
			{/if}
		</div>
	{/if}
	<div class="p-4">
		{@render children()}
	</div>
</section>
