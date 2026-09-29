<!--
	docs/layout.md#a-page. A page's title and one sentence on the canvas, with
	the page's own actions at the right; where they do not fit beside the
	title (a phone), the actions wrap under the sentence. It has no margin of
	its own: it comes first in the page's column, whose gap
	(gap-(--gap-panels)) sets it 16px above the first panel.

	<PageHeader title="Machines" description="Every sorter on your account.">
		{#snippet actions()}<Button icon={Plus}>Add a machine</Button>{/snippet}
	</PageHeader>
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
		// One sentence: what the page is for.
		description?: string;
		actions?: Snippet;
		// More under the sentence: a link back, a status.
		children?: Snippet;
	} = $props();
</script>

<header class="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
	<div class="min-w-0 flex-[1_1_20rem]">
		<h1 class="text-xl font-semibold tracking-tight text-ink">{title}</h1>
		{#if description}<p class="mt-1 max-w-prose text-sm text-ink-muted">{description}</p>{/if}
		{#if children}<div class="mt-2">{@render children()}</div>{/if}
	</div>
	{#if actions}<div class="flex flex-wrap items-center gap-2">{@render actions()}</div>{/if}
</header>
