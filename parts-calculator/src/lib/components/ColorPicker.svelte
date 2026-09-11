<script lang="ts">
	import { BAMBU_COLORS, getBambuColor, type BambuColor } from '$lib/bambu-colors';

	let {
		value = $bindable(),
		label
	}: { value: string; label: string } = $props();

	let open = $state(false);
	const current = $derived(getBambuColor(value));

	// LEGO builders know "light bluish gray", not "Ash Gray", so every swatch that
	// has a real LEGO counterpart names it (BrickLink naming, see bambu-colors.ts).
	const legoTitle = (c: BambuColor) => (c.lego ? `${c.name} · LEGO ${c.lego.name}` : c.name);

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
		<span class="h-5 w-5 shrink-0 border border-border" style="background:{current.hex}"></span>
		<span class="min-w-0 flex-1 leading-tight">
			{current.name}
			{#if current.lego}
				<span class="block text-[11px] leading-tight text-text-muted">LEGO {current.lego.name}</span>
			{/if}
		</span>
		<span class="text-text-muted">▾</span>
	</button>

	{#if open}
		<div
			class="setup-panel absolute z-20 mt-1 grid max-h-72 w-72 grid-cols-8 gap-1 overflow-y-auto p-2"
		>
			{#each BAMBU_COLORS as c (c.id)}
				<button
					type="button"
					title={legoTitle(c)}
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
