<!--
	docs/layout.md#settings. One setting: its name and a sentence on the left,
	its control on the right; stacked on a narrow screen. Rows go in a
	`divide-y divide-line` list inside a flush Panel, so a line sits only
	between two rows, never above the first or below the last.

	`below` holds what belongs to the setting but is wider than a control (a
	chart, a set of sub-settings): it renders under the row, in a well.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		label,
		help,
		for: forId,
		children,
		below
	}: {
		label: string;
		help?: string;
		for?: string;
		children?: Snippet;
		below?: Snippet;
	} = $props();
</script>

<div class="px-(--pad-panel) py-(--pad-row)">
	<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
		<div class="min-w-0">
			{#if forId}
				<label for={forId} class="text-sm font-medium text-ink">{label}</label>
			{:else}
				<div class="text-sm font-medium text-ink">{label}</div>
			{/if}
			{#if help}<p class="mt-0.5 max-w-prose text-sm text-ink-muted">{help}</p>{/if}
		</div>
		{#if children}<div class="flex shrink-0 items-center gap-2">{@render children()}</div>{/if}
	</div>
	{#if below}<div class="mt-3 overflow-hidden rounded-control bg-well">{@render below()}</div>{/if}
</div>
