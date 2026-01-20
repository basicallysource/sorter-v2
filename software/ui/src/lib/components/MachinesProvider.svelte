<script lang="ts">
	import { MachineManager } from '$lib/machines/manager.svelte';
	import { setMachinesContext } from '$lib/machines/context';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	const manager = new MachineManager();
	setMachinesContext(manager);
</script>

{@render children()}
