<script lang="ts">
	import Modal from '$lib/components/Modal.svelte';
	import HardwareDetail from '$lib/components/HardwareDetail.svelte';
	import type { Hardware } from '$lib/filament';

	// Thin modal wrapper around the shared HardwareDetail view, used by the hardware
	// page and the assembly tab so both open the same thing. The standalone
	// /part/<id> page renders the very same HardwareDetail without a modal around it.
	// `showCart` + `selected` wire the Amazon-cart checkbox on the hardware page;
	// callers without a cart leave them off.
	let {
		open = $bindable(false),
		hardware,
		layers,
		showCart = false,
		selected = $bindable({})
	}: {
		open?: boolean;
		hardware: Hardware | null;
		layers: number;
		showCart?: boolean;
		selected?: Record<string, boolean>;
	} = $props();
</script>

<Modal bind:open title={hardware?.name} maxW="max-w-4xl">
	{#if hardware}
		<HardwareDetail {hardware} {layers} {showCart} bind:selected />
	{/if}
</Modal>
