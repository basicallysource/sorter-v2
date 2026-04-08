<script lang="ts">
	import { getMachinesContext } from '$lib/machines/context';
	import { ChevronDown } from 'lucide-svelte';

	const manager = getMachinesContext();

	let dropdown_open = $state(false);

	const selected = $derived(manager.selectedMachine);
	const machines = $derived([...manager.machines.entries()]);

	function toggleDropdown() {
		dropdown_open = !dropdown_open;
	}

	function selectMachine(id: string) {
		manager.selectMachine(id);
		dropdown_open = false;
	}

	function handleClickOutside(event: MouseEvent) {
		const target = event.target as HTMLElement;
		if (!target.closest('.machine-dropdown')) {
			dropdown_open = false;
		}
	}
</script>

<svelte:window onclick={handleClickOutside} />

<div class="machine-dropdown relative">
	<button
		type="button"
		onclick={toggleDropdown}
		class="flex items-center gap-2 border border-border bg-surface px-3 py-1.5 text-sm text-text transition-colors hover:bg-bg"
	>
		{#if selected}
			<span
				class="h-2 w-2 rounded-full {selected.status === 'connected'
					? 'bg-[#00852B]'
					: 'bg-[#D01012]'}"
			></span>
			<span class="max-w-32 truncate">
				{selected.identity?.nickname ?? selected.identity?.machine_id.slice(0, 8) ?? 'Unknown'}
			</span>
		{:else}
			<span class="h-2 w-2 rounded-full bg-gray-500"></span>
			<span class="text-text-muted">No machine</span>
		{/if}
		<ChevronDown size={14} class="opacity-60" />
	</button>

	{#if dropdown_open && machines.length > 0}
		<div
			class="absolute top-full right-0 z-50 mt-1 min-w-48 border border-border bg-surface shadow-lg"
		>
			{#each machines as [id, m]}
				<button
					type="button"
					onclick={() => selectMachine(id)}
					class="flex w-full items-center gap-2 px-3 py-2 text-left text-sm transition-colors {id ===
					manager.selectedMachineId
						? 'bg-primary/20 text-primary'
						: 'text-text hover:bg-bg'}"
				>
					<span
						class="h-2 w-2 rounded-full {m.status === 'connected' ? 'bg-[#00852B]' : 'bg-[#D01012]'}"
					></span>
					<span class="truncate">
						{m.identity?.nickname ?? id.slice(0, 8)}
					</span>
				</button>
			{/each}
		</div>
	{/if}
</div>
