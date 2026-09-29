<script lang="ts">
	import Input from '$lib/components/ui/Input.svelte';
	import Search from '@lucide/svelte/icons/search';
	import X from '@lucide/svelte/icons/x';

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

<div class="mb-4 border border-line bg-surface px-4 py-3">
	<div class="flex items-center gap-3">
		<Search size={16} class="shrink-0 text-ink-muted" />
		<Input
			type="search"
			bind:value={query}
			placeholder="Find a part, color, or category — matching bins light up"
		/>
		{#if query}
			<button
				type="button"
				onclick={() => (query = '')}
				class="flex shrink-0 items-center gap-1.5 border border-line bg-surface px-2.5 py-2 text-sm text-ink-muted transition-colors hover:bg-hover hover:text-ink"
				title="Clear search"
			>
				<X size={14} />
				Clear
			</button>
		{/if}
	</div>
	{#if matchCount !== null}
		<div class="mt-2 text-sm {matchCount === 0 ? 'text-warning-ink' : 'text-ink-muted'}">
			{matchCount === 0
				? 'No bins match — the part may have gone to the discard passthrough.'
				: `${matchCount} of ${totalBins} bin${totalBins === 1 ? '' : 's'} match — highlighted below.`}
		</div>
	{/if}
</div>
