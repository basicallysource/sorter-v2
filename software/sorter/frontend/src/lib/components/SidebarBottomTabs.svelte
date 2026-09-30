<script lang="ts">
	import Tabs from '$lib/components/ui/Tabs.svelte';
	import RuntimeStats from './RuntimeStats.svelte';
	import StateMachineLive from './StateMachineLive.svelte';
	import BusMessageTicker from './BusMessageTicker.svelte';

	type Tab = 'stats' | 'states' | 'bus';
	let active = $state<Tab>('stats');
</script>

<div class="flex h-full min-h-0 flex-col">
	<Tabs
		label="Runtime"
		inset
		bind:value={active}
		items={[
			{ value: 'stats', label: 'Stats' },
			{ value: 'states', label: 'Live states' },
			{ value: 'bus', label: 'Bus ticker' }
		]}
	/>
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
