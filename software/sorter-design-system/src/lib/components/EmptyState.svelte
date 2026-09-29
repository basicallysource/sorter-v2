<!--
	docs/components.md#empty-state. What an empty list, table or feed shows:
	a well with a sentence saying what would be here and, when there is one,
	the action that fills it.
-->
<script lang="ts">
	import type { Component, Snippet } from 'svelte';

	let {
		icon: Icon,
		title,
		children,
		action
	}: {
		icon?: Component<{ size?: number; class?: string }>;
		title: string;
		children?: Snippet;
		action?: Snippet;
	} = $props();
</script>

<div class="flex flex-col items-center gap-2 rounded-control bg-well px-6 py-10 text-center">
	{#if Icon}<Icon size={24} class="text-ink-faint" />{/if}
	<div class="text-sm font-medium text-ink">{title}</div>
	{#if children}<p class="max-w-sm text-sm text-ink-muted">{@render children()}</p>{/if}
	{#if action}<div class="mt-2">{@render action()}</div>{/if}
</div>
