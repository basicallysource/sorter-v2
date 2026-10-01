<!--
	docs/components.md#forms. A label over its control, and one sentence under
	it: help in muted ink, or the error in danger ink (which replaces the help).
	Give the control the same `id` as `for`, and `aria-invalid` when `error`.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		label,
		for: forId,
		help,
		error,
		children,
		class: className = ''
	}: {
		label: string;
		for: string;
		help?: string;
		error?: string;
		children: Snippet;
		class?: string;
	} = $props();
</script>

<div class="flex flex-col gap-1.5 {className}">
	<label for={forId} class="text-sm font-medium text-ink">{label}</label>
	{@render children()}
	{#if error}
		<p class="text-sm text-danger-ink">{error}</p>
	{:else if help}
		<p class="text-sm text-ink-muted">{help}</p>
	{/if}
</div>
