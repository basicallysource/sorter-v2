<script lang="ts">
	import { getMachinesContext, setMachineContext } from '$lib/machines/context';
	import type { MachineContext } from '$lib/machines/types';
	import type { Snippet } from 'svelte';

	let { children }: { children: Snippet } = $props();

	const manager = getMachinesContext();

	const ctx: MachineContext = {
		get machine() {
			return manager.selectedMachine;
		},
		get frames() {
			return manager.selectedMachine?.frames ?? new Map();
		},
		sendCommand(command: unknown) {
			manager.sendCommand(command);
		}
	};

	setMachineContext(ctx);
</script>

{@render children()}
