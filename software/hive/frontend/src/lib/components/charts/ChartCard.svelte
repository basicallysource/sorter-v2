<!--
	A chart in a panel: the panel's title and one sentence, and the chart on a
	well (the design system's docs/components.md, Charts).
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Panel from '$lib/components/Panel.svelte';

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

<Panel {title} description={subtitle || undefined}>
	<div class="rounded-control bg-well p-3">{@render children()}</div>
</Panel>
