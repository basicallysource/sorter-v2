<script lang="ts">
	import { BAMBU_COLORS, getBambuColor } from '$lib/bambu-colors';

	let {
		value = $bindable(),
		label
	}: { value: string; label: string } = $props();

	let open = $state(false);
	const current = $derived(getBambuColor(value));

	function pick(id: string) {
		value = id;
		open = false;
	}

	function onWindowClick(e: MouseEvent) {
		if (!(e.target as HTMLElement).closest('[data-colorpicker]')) open = false;
	}
</script>

<svelte:window onclick={onWindowClick} />

<div class="relative" data-colorpicker>
	<span class="mb-1 block text-xs font-semibold uppercase tracking-wider text-text-muted">{label}</span>
	<button
		type="button"
		class="setup-control flex w-full items-center gap-2 px-3 text-left text-sm"
		onclick={() => (open = !open)}
	>
		<span class="h-5 w-5 border border-border" style="background:{current.hex}"></span>
		<span class="flex-1">{current.name}</span>
		<span class="text-text-muted">▾</span>
	</button>

	{#if open}
		<div
			class="setup-panel absolute z-20 mt-1 grid max-h-72 w-72 grid-cols-8 gap-1 overflow-y-auto p-2"
		>
			{#each BAMBU_COLORS as c (c.id)}
				<button
					type="button"
					title={c.name}
					onclick={() => pick(c.id)}
					class="h-7 w-7 border {c.id === value
						? 'border-primary ring-2 ring-primary'
						: 'border-border'}"
					style="background:{c.hex}"
					aria-label={c.name}
				></button>
			{/each}
		</div>
	{/if}
</div>
