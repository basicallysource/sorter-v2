<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title = '',
		description = '',
		rootClass = '',
		headerClass = '',
		bodyClass = '',
		children
	}: {
		title?: string;
		description?: string;
		rootClass?: string;
		headerClass?: string;
		bodyClass?: string;
		children: Snippet;
	} = $props();
</script>

<section class={`overflow-hidden border border-border ${rootClass}`.trim()}>
	{#if title}
		<div class={`border-b border-border bg-surface px-4 py-3 ${headerClass}`.trim()}>
			<h2 class="text-base font-semibold text-text">{title}</h2>
			{#if description}
				<p class="mt-1 text-sm text-text-muted">{description}</p>
			{/if}
		</div>
	{/if}
	<div class={`p-4 ${bodyClass}`.trim()}>
		{@render children()}
	</div>
</section>
