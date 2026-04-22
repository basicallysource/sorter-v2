<script lang="ts">
	import RuntimeStats from './RuntimeStats.svelte';
	import StateMachineLive from './StateMachineLive.svelte';
	import BusMessageTicker from './BusMessageTicker.svelte';

	type Tab = 'stats' | 'states' | 'bus';
	let active = $state<Tab>('stats');

	const TABS: { id: Tab; label: string }[] = [
		{ id: 'stats', label: 'Runtime Stats' },
		{ id: 'states', label: 'Live States' },
		{ id: 'bus', label: 'Bus Ticker' }
	];

	function tabClass(id: Tab): string {
		const base = 'flex-1 border-b-2 px-3 py-1.5 text-sm transition-colors';
		if (active === id) return `${base} border-primary text-text`;
		return `${base} border-transparent text-text-muted hover:text-text`;
	}
</script>

<div class="flex h-full min-h-0 flex-col border border-border bg-surface">
	<div class="flex shrink-0 border-b border-border">
		{#each TABS as tab (tab.id)}
			<button type="button" class={tabClass(tab.id)} onclick={() => (active = tab.id)}>
				{tab.label}
			</button>
		{/each}
	</div>
	<div class="min-h-0 flex-1">
		{#if active === 'stats'}
			<RuntimeStats />
		{:else if active === 'states'}
			<StateMachineLive />
		{:else}
			<BusMessageTicker />
		{/if}
	</div>
</div>
