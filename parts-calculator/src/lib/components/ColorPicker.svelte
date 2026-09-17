<script lang="ts">
	import { Anchored, tip } from '$lib/popover';
	import { BAMBU_COLORS, getBambuColor, type BambuColor } from '$lib/bambu-colors';

	let {
		value = $bindable(),
		label
	}: { value: string; label: string } = $props();

	let open = $state(false);
	let root = $state<HTMLElement | null>(null);
	const current = $derived(getBambuColor(value));

	// LEGO builders know "light bluish gray", not "Ash Gray", so every swatch that
	// has a real LEGO counterpart names it (BrickLink naming, see bambu-colors.ts).
	const legoTitle = (c: BambuColor) => (c.lego ? `${c.name} · LEGO ${c.lego.name}` : c.name);

	function pick(id: string) {
		value = id;
		open = false;
	}
</script>

<div bind:this={root}>
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

</div>

<!-- In the floating layer, so the grid is not cut off by the setup card it
     drops out of, and so it can flip above the control near the foot of the
     page. -->
{#if open}
	<Anchored anchor={root} class="setup-panel w-72 p-2" maxHeight="18rem" onDismiss={() => (open = false)}>
		<div class="grid grid-cols-8 gap-1">
			{#each BAMBU_COLORS as c (c.id)}
				<button
					type="button"
					use:tip={legoTitle(c)}
					onclick={() => pick(c.id)}
					class="h-7 w-7 border {c.id === value
						? 'border-primary ring-2 ring-primary'
						: 'border-border'}"
					style="background:{c.hex}"
					aria-label={c.name}
				></button>
			{/each}
		</div>
	</Anchored>
{/if}
