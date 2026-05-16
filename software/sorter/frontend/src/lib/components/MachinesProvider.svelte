<script lang="ts">
	import { backendWsBaseUrl } from '$lib/backend';
	import { MachineManager } from '$lib/machines/manager.svelte';
	import { setMachinesContext } from '$lib/machines/context';
	import { onMount } from 'svelte';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	const manager = new MachineManager();
	setMachinesContext(manager);

	onMount(() => {
		const url = `${backendWsBaseUrl}/ws`;
		manager.ensureConnected(url);
		return manager.startConnectionWatchdog({ defaultUrl: url });
	});
</script>

{@render children()}
