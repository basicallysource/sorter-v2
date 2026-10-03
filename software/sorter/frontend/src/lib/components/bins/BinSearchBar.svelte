<script lang="ts">
	import Button from '$lib/components/ui/Button.svelte';
	import Input from '$lib/components/ui/Input.svelte';

	let {
		query = $bindable(''),
		matchCount,
		totalBins
	}: {
		query?: string;
		matchCount: number | null;
		totalBins: number;
	} = $props();
</script>

<div class="flex flex-col gap-2">
	<Input
		bind:value={query}
		aria-label="Find a bin"
		placeholder="Find a part, color or category"
		class="max-w-xl"
	>
		{#snippet end()}
			{#if query}<Button size="sm" variant="ghost" onclick={() => (query = '')}>Clear</Button>{/if}
		{/snippet}
	</Input>
	{#if matchCount !== null}
		<p class="text-sm {matchCount === 0 ? 'text-warning-ink' : 'text-ink-muted'}">
			{matchCount === 0
				? 'No bins match. The part may have gone to the discard passthrough.'
				: `${matchCount} of ${totalBins} bin${totalBins === 1 ? '' : 's'} match and are highlighted below.`}
		</p>
	{/if}
</div>
