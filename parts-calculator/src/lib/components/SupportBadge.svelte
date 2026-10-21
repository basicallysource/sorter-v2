<script lang="ts">
	// The "Support needed" marking: a part that has to be printed with support
	// material. One component so the calculator rows, the assembly pages and the
	// part viewer all carry the same tag. Renders nothing for a part that prints
	// without supports.
	import Badge from '$lib/components/Badge.svelte';
	import type { Part } from '$lib/filament';

	let { part }: { part: Part } = $props();
</script>

{#if part.support_intentional}
	<Badge variant="info" tipText="Printed with support material, included in this part's grams">Support needed</Badge>
{/if}
